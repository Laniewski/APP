"""Local llama-server transport; model messages in, parsed JSON out."""

import http.client
import json
import logging
import socket
import subprocess
import threading
import time

from .prompt_loader import load_messages
from .plan_schema import response_schema
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
        self.last_messages = []

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
        self.last_messages = []
        self.last_metrics = {}
        if self._closed.is_set():
            raise RuntimeError("Backend asystenta został zamknięty.")
        messages = load_messages(request) if isinstance(request, str) else request
        if not isinstance(messages, list) or not messages:
            raise ValueError("Wymagane messages z prompt_loader.")
        self._cancelled.clear()
        if stop_event is not None and stop_event.is_set():
            self._cancelled.set()
            raise RuntimeError("Generowanie anulowane.")
        self.ensure_ready(status)
        status("Generowanie odpowiedzi...")
        logger.info("Rozpoczęcie generowania odpowiedzi.")
        self.last_messages = messages
        payload = {"messages": messages, "temperature": 0.0, "max_tokens": 2048,
                   "response_format": {"type": "json_object"},
                   "chat_template_kwargs": {"enable_thinking": False}}
        if self.config.schema_in_response_format:
            payload["response_format"]["schema"] = response_schema()
        else:
            payload["json_schema"] = response_schema()
        if self.config.debug_io:
            self.config.runs_dir.mkdir(parents=True, exist_ok=True)
            (self.config.runs_dir / "last_model_input.txt").write_text(
                json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8")
        started = time.monotonic()
        response = self._request("POST", "/v1/chat/completions", payload)
        choice = response["choices"][0]
        text = choice["message"]["content"]
        self.last_raw_response = text
        if self.config.debug_io:
            (self.config.runs_dir / "last_model_response.json").write_text(text, encoding="utf-8")
        elapsed = time.monotonic() - started
        usage = response.get("usage", {})
        self.last_metrics = {**usage, "elapsed_s": elapsed, "requests": 1,
                             "tokens_per_s": usage.get("completion_tokens", 0) / max(elapsed, 1e-9)}
        if self._cancelled.is_set() or (stop_event is not None and stop_event.is_set()):
            raise RuntimeError("Generowanie anulowane.")
        if choice.get("finish_reason") == "length":
            raise ValueError("Odpowiedź modelu została obcięta; skróć polecenie lub materiały.")
        return parse_response(text)

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
