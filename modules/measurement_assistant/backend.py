"""Lokalny llama-server: lazy loading, JSON i jedna próba naprawy formatu."""

import http.client
import json
import logging
import socket
import subprocess
import threading
import time

from .actions import ACTION_REGISTRY
from .config import AssistantConfig
from .plan_schema import (parse_response, response_schema, requires_unsupported_stabilization,
                          STABILIZATION_MISSING)

logger = logging.getLogger(__name__)


def system_prompt():
    registry = [{"name": spec.name, "description": spec.description,
                 "arguments": {key: arg.schema() for key, arg in spec.arguments.items()},
                 "required_arguments": list(spec.arguments)}
                for spec in ACTION_REGISTRY.values()]
    return (
        "You plan laboratory measurement procedures. Answer in Polish, ONLY with a JSON object "
        "with title (string), steps (list of {description, action, args}), missing_parameters "
        "(list of strings), notes (list of strings). No other fields. "
        "Use ONLY the actions below. Never generate Python, shell commands or new actions. "
        "Never invent missing values. Put missing required information in missing_parameters. "
        "Include EVERY requested supported action in steps, in the user's order. "
        "missing_parameters must be EMPTY [] when all required values are explicitly given. "
        "missing_parameters contains human-readable QUESTIONS about absent values or unsupported operations, "
        "NEVER action names. start_measurement and stop_measurement require no arguments, use args {}. "
        "Descriptions are for the human only. Require arguments ONLY for actions the user requested, "
        "never for unused actions. A piezo measurement does NOT require paddle or angle_deg. "
        "Temperature setpoint is NOT heater activation or temperature stabilization. "
        "'Wait until stabilized' requires explicit stabilization criteria and an action we do not yet support: "
        "report this in missing_parameters; NEVER replace it by an invented wait duration. "
        "ONLY if the current user actually requests temperature stabilization, ask for tolerance and stability time "
        "and state that stabilization is not yet supported. Never ask these for a plain timed piezo measurement. "
        "Do not claim that a plan is runnable. Hardware must already be connected manually. "
        "Available actions: " + json.dumps(registry, ensure_ascii=False)
        + '\nExample request: Ustaw piezo na 12 V, rozpocznij pomiar, poczekaj 3 sekundy, zatrzymaj pomiar.'
        + '\nExample correct response: '
        + json.dumps({"title": "Pomiar piezo", "steps": [
            {"description": "Ustaw piezo na 12 V", "action": "set_piezo_voltage", "args": {"value_v": 12}},
            {"description": "Rozpocznij pomiar", "action": "start_measurement", "args": {}},
            {"description": "Poczekaj 3 sekundy", "action": "wait", "args": {"seconds": 3}},
            {"description": "Zatrzymaj pomiar", "action": "stop_measurement", "args": {}},
        ], "missing_parameters": [], "notes": []}, ensure_ascii=False)
        + 'The example values 12 and 3 are NOT defaults. Use only values from the current user request.'
    )


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

    def ensure_ready(self, status):
        if self._closed.is_set() or self._cancelled.is_set():
            raise RuntimeError("Backend asystenta został zatrzymany.")
        if self.is_ready():
            status("Model gotowy")
            return
        if not self.config.binary.is_file() or not self.config.model.is_file():
            raise FileNotFoundError("Brak llama-server lub modelu GGUF. Zobacz docs/measurement_assistant.md.")
        status("Ładowanie modelu...")
        logger.info("Start lokalnego llama-server na %s", self.config.url)
        with self._process_lock:
            if self._closed.is_set() or self._cancelled.is_set():
                raise RuntimeError("Backend asystenta został zatrzymany.")
            if self._process is None or self._process.poll() is not None:
                self.config.model.parent.mkdir(parents=True, exist_ok=True)
                if self._server_log:
                    self._server_log.close()
                self._server_log = open(self.config.model.parent / "llama-server.log", "a", encoding="utf-8")
                self._process = subprocess.Popen([
                    str(self.config.binary), "-m", str(self.config.model),
                    "--host", "127.0.0.1", "--port", str(self.config.port),
                    "-c", str(self.config.context_size), "-t", str(self.config.threads),
                    "-b", "256", "-ub", "128",
                    "--cache-ram", "0",
                    "-ngl", "0", "--parallel", "1",
                ], stdout=self._server_log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if self._cancelled.wait(0.2):
                raise RuntimeError("Generowanie anulowane.")
            if self._process.poll() is not None:
                raise RuntimeError("llama-server zakończył się podczas ładowania. Sprawdź llama-server.log.")
            if self.is_ready():
                status("Model gotowy")
                logger.info("Lokalny model gotowy.")
                return
        raise TimeoutError("Model nie osiągnął gotowości w 90 s.")

    def generate(self, request, status=lambda message: None, stop_event=None):
        self.last_raw_response = None
        if self._closed.is_set():
            raise RuntimeError("Backend asystenta został zamknięty.")
        if not isinstance(request, str) or not 1 <= len(request.strip()) <= 4000:
            raise ValueError("Opis musi zawierać od 1 do 4000 znaków.")
        self._cancelled.clear()
        if stop_event is not None and stop_event.is_set():
            self._cancelled.set()
            raise RuntimeError("Generowanie anulowane.")
        self.ensure_ready(status)
        status("Generowanie planu...")
        logger.info("Rozpoczęcie generowania planu.")
        messages = [{"role": "system", "content": system_prompt()},
                    {"role": "user", "content": request}]
        if requires_unsupported_stabilization(request):
            messages[-1]["content"] += (
                "\nImportant: temperature stabilization is unsupported. Include only the supported "
                "setpoint/piezo/measurement actions requested above, NO wait for stabilization. "
                "missing_parameters must contain: " + STABILIZATION_MISSING
            )
        started = time.monotonic()
        for attempt in range(2):
            response = self._request("POST", "/v1/chat/completions", {
                "messages": messages, "temperature": 0, "max_tokens": 768,
                "response_format": {"type": "json_object"},
                "json_schema": response_schema(),
            })
            try:
                text = response["choices"][0]["message"]["content"]
                plan = parse_response(text)
                self.last_raw_response = text
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                logger.warning("Błąd JSON modelu (próba %s): %s", attempt + 1, exc)
                if attempt:
                    raise ValueError("Model dwukrotnie zwrócił niepoprawny JSON.") from exc
                messages.append({"role": "user", "content": "Previous response was not valid JSON. Return only the required JSON object, no markdown."})
                continue
            elapsed = time.monotonic() - started
            # Bezpieczeństwo nie zależy od przestrzegania promptu przez mały model.
            # Zachowujemy odpowiedź do wglądu, ale żaden taki plan nie dostanie script.py.
            if requires_unsupported_stabilization(request):
                missing = plan.get("missing_parameters")
                if isinstance(missing, list) and STABILIZATION_MISSING not in missing:
                    missing.append(STABILIZATION_MISSING)
                steps = plan.get("steps")
                if isinstance(steps, list):
                    kept = [step for step in steps if not (
                        isinstance(step, dict) and step.get("action") == "wait"
                        and requires_unsupported_stabilization(step.get("description"))
                    )]
                    if len(kept) != len(steps):
                        plan["steps"] = kept
                        if isinstance(plan.get("notes"), list):
                            plan["notes"].append("Odrzucono błędny krok wait zastępujący stabilizację. Oryginalna odpowiedź jest w llm_response.json; plan pozostaje zablokowany.")
                logger.warning("Plan stabilizacji zablokowany niezależnie od deklaracji LLM.")
            tokens = response.get("usage", {}).get("completion_tokens", 0)
            timings = response.get("timings", {})
            end_to_end_rate = tokens / elapsed if elapsed else 0
            self.last_metrics = {"elapsed_s": elapsed, "completion_tokens": tokens,
                                 "tokens_per_s": timings.get("predicted_per_second", end_to_end_rate),
                                 "end_to_end_tokens_per_s": end_to_end_rate,
                                 "timings": timings}
            logger.info("Plan wygenerowany w %.2f s (%s tokenów).", elapsed, tokens)
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
