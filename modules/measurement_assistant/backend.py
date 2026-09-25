"""Lokalny llama-server: lazy loading, JSON i jedna próba naprawy formatu."""

import http.client
import json
import logging
import socket
import subprocess
import threading
import time

from .context_builder import system_prompt, extraction_schema
from .grounding import segments, grounded_plan
from .config import AssistantConfig
from .plan_schema import parse_response

logger = logging.getLogger(__name__)


class LLMBackend:
    def __init__(self, config=None):
        self.config = config or AssistantConfig.from_env()
        self._process = None
        self._server_log = None
        self._connection = None
        self._lock = threading.Lock()
        self._process_lock = threading.Lock()
        self._closed = threading.Event()
        self._cancelled = threading.Event()
        self.last_metrics = {}
        self.last_raw_response = None

    def _request(self, method, path, payload=None, timeout=None):
        if self._cancelled.is_set():
            raise RuntimeError("Generowanie anulowane.")
        connection = http.client.HTTPConnection("127.0.0.1", self.config.port,
                                                timeout=timeout or self.config.timeout_s)
        with self._lock:
            self._connection = connection
        try:
            body = json.dumps(payload).encode("utf-8") if payload is not None else None
            connection.request(method, path, body=body, headers={"Content-Type": "application/json"})
            if self._cancelled.is_set():
                raise RuntimeError("Generowanie anulowane.")
            response = connection.getresponse()
            raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise RuntimeError("Zbyt duża odpowiedź llama-server.")
            if response.status != 200:
                raise RuntimeError(f"llama-server HTTP {response.status}: {raw[:300].decode('utf-8', errors='replace')}")
            return json.loads(raw)
        finally:
            connection.close()
            with self._lock:
                if self._connection is connection:
                    self._connection = None

    def is_ready(self):
        try:
            return self._request("GET", "/health", timeout=1).get("status") == "ok"
        except (OSError, RuntimeError, ValueError):
            return False

    def _port_in_use(self):
        try:
            with socket.create_connection(("127.0.0.1", self.config.port), timeout=1):
                return True
        except OSError:
            return False

    def ensure_ready(self, status):
        if self._closed.is_set() or self._cancelled.is_set():
            raise RuntimeError("Backend asystenta został zatrzymany.")
        if self.is_ready():
            status("Model gotowy")
            return
        status("Ładowanie modelu...")
        # Zewnętrzny serwer może już nasłuchiwać, lecz zwracać 503 podczas ładowania.
        if not self._port_in_use():
            if not self.config.binary.is_file() or not self.config.model.is_file():
                raise FileNotFoundError("Brak llama-server lub modelu GGUF. Zobacz docs/measurement_assistant.md.")
            logger.info("Start lokalnego llama-server na %s", self.config.url)
            with self._process_lock:
                if self._closed.is_set() or self._cancelled.is_set():
                    raise RuntimeError("Backend asystenta został zatrzymany.")
                if self._process is None or self._process.poll() is not None:
                    self.config.runs_dir.mkdir(parents=True, exist_ok=True)
                    if self._server_log:
                        self._server_log.close()
                    self._server_log = open(self.config.runs_dir / "llama-server.log", "a", encoding="utf-8")
                    self._process = subprocess.Popen([
                        str(self.config.binary), "-m", str(self.config.model),
                        "--host", "127.0.0.1", "--port", str(self.config.port),
                        "-c", str(self.config.context_size), "-t", str(self.config.threads),
                        "-b", "256", "-ub", "128",
                        "--cache-ram", "0",
                        "-ngl", "0", "--parallel", "1", "--no-mmproj", "--reasoning", "off",
                    ], stdout=self._server_log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if self._cancelled.wait(0.2):
                raise RuntimeError("Generowanie anulowane.")
            if self._process is not None and self._process.poll() is not None:
                raise RuntimeError("llama-server zakończył się podczas ładowania. Sprawdź llama-server.log.")
            if self.is_ready():
                status("Model gotowy")
                logger.info("Lokalny model gotowy.")
                return
        raise TimeoutError("Model nie osiągnął gotowości w 90 s.")

    def generate(self, request, status=lambda message: None, stop_event=None):
        self.last_raw_response = None
        self.last_metrics = {}
        if self._closed.is_set():
            raise RuntimeError("Backend asystenta został zamknięty.")
        if not isinstance(request, str) or not request.strip() or len(request) > 4000:
            raise ValueError("Opis musi zawierać od 1 do 4000 znaków.")
        self._cancelled.clear()
        if stop_event is not None and stop_event.is_set():
            self._cancelled.set()
            raise RuntimeError("Generowanie anulowane.")
        self.ensure_ready(status)
        status("Generowanie planu...")
        logger.info("Rozpoczęcie generowania planu.")
        fragments = segments(request)
        if len(fragments) > 50:
            raise ValueError("Za dużo czynności; podziel polecenie (maksymalnie 50 fragmentów).")
        started = time.monotonic()
        raw_responses, extracted, usages = [], [], []
        for offset in range(0, len(fragments), 3):
            if self._cancelled.is_set() or (stop_event is not None and stop_event.is_set()):
                raise RuntimeError("Generowanie anulowane.")
            status(f"Ekstrakcja fragmentów {offset + 1}–{min(offset + 3, len(fragments))}/{len(fragments)}...")
            batch = [{"id": i, "text": fragments[i][2]} for i in range(offset, min(offset + 3, len(fragments)))]
            if sum(len(item["text"]) for item in batch) > 1000:
                raise ValueError("Fragment polecenia jest za długi dla kontekstu modelu; podziel opis.")
            messages = [{"role": "system", "content": system_prompt()},
                        {"role": "user", "content": json.dumps(batch, ensure_ascii=False)}]
            for attempt in range(2):
                payload = {"messages": messages, "temperature": 0.0, "max_tokens": 400,
                           "response_format": {"type": "json_object"},
                           "chat_template_kwargs": {"enable_thinking": False}}
                if self.config.schema_in_response_format:
                    payload["response_format"]["schema"] = extraction_schema([item["id"] for item in batch])
                else:
                    payload["json_schema"] = extraction_schema([item["id"] for item in batch])
                response = self._request("POST", "/v1/chat/completions", payload)
                if self._cancelled.is_set() or (stop_event is not None and stop_event.is_set()):
                    raise RuntimeError("Generowanie anulowane.")
                usage = response.get("usage", {})
                usages.append({**usage, "timings": response.get("timings", {})})
                self.last_metrics = {"elapsed_s": time.monotonic() - started,
                                     "completion_tokens": sum(u.get("completion_tokens", 0) for u in usages),
                                     "prompt_tokens": sum(u.get("prompt_tokens", 0) for u in usages),
                                     "requests": len(usages), "usage_by_request": usages}
                try:
                    text = response["choices"][0]["message"]["content"]
                    raw_responses.append(text)
                    self.last_raw_response = json.dumps(raw_responses, ensure_ascii=False)
                    parsed = parse_response(text)
                    rows = parsed.get("steps")
                    if set(parsed) != {"steps"} or not isinstance(rows, list):
                        raise ValueError("Wymagane steps.")
                    ids = {item["id"] for item in batch}
                    for row in rows:
                        if (not isinstance(row, dict) or set(row) != {"id", "action", "args"}
                            or type(row["id"]) is not int or row["id"] not in ids
                            or not isinstance(row["action"], str) or not isinstance(row["args"], dict)):
                            raise ValueError("Nieprawidłowy krok ekstrakcji.")
                    if response["choices"][0].get("finish_reason") == "length":
                        raise ValueError("Odpowiedź obcięta.")
                    extracted.extend(rows)
                    break
                except (KeyError, IndexError, TypeError, ValueError) as exc:
                    if attempt:
                        raise ValueError(f"Model dwukrotnie zwrócił błędną ekstrakcję: {exc}") from exc
                    messages.append({"role": "user", "content": "Zwróć poprawny JSON steps z id każdego fragmentu."})
        plan = grounded_plan(request)
        expected = []
        for i, (start, end, _) in enumerate(fragments):
            expected.extend({"id": i, "action": step["action"], "args": step["args"]}
                            for step in plan["steps"] if step["source"] == [start, end])
        if extracted != expected:
            plan["notes"].append("Ekstrakcja modelu różniła się od interpretacji źródła. Plan wyznaczono ograniczoną gramatyką; nierozpoznane fragmenty zablokowano.")
        elapsed = time.monotonic() - started
        tokens = sum(u.get("completion_tokens", 0) for u in usages)
        predicted_ms = sum(u.get("timings", {}).get("predicted_ms", 0) for u in usages)
        self.last_metrics = {"elapsed_s": elapsed, "completion_tokens": tokens,
                             "prompt_tokens": sum(u.get("prompt_tokens", 0) for u in usages),
                             "tokens_per_s": tokens * 1000 / predicted_ms if predicted_ms else tokens / elapsed,
                             "end_to_end_tokens_per_s": tokens / elapsed,
                             "requests": len(usages), "usage_by_request": usages,
                             "extracted_steps": extracted, "model_agrees": extracted == expected}
        return plan

    def cancel(self):
        self._cancelled.set()
        with self._lock:
            connection = self._connection
            if connection:
                if connection.sock:
                    try:
                        connection.sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                connection.close()

    def shutdown(self):
        self._closed.set()
        self.cancel()
        with self._process_lock:
            if self._process is not None and self._process.poll() is None:
                self._process.terminate()
                try:
                    self._process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait(timeout=2)
            if self._server_log:
                self._server_log.close()
                self._server_log = None
