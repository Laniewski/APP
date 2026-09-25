"""Konfiguracja lokalnego modelu; żaden parametr nie pochodzi z planu AI."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AssistantConfig:
    binary: Path = Path.home() / ".local/share/app-v2/llama.cpp/build/bin/llama-server"
    model: Path = Path.home() / ".local/share/app-v2/models/qwen2.5-1.5b-instruct-q4_k_m.gguf"
    execution_enabled: bool = False
    schema_in_response_format: bool = True
    port: int = 8080
    context_size: int = 2048
    threads: int = 3
    timeout_s: float = 120.0
    runs_dir: Path = Path(__file__).resolve().parents[2] / "runs"

    @classmethod
    def from_env(cls):
        defaults = cls()
        execution = os.getenv("APP_AI_EXECUTION_ENABLED", "0").strip().lower()
        if execution not in {"0", "1", "false", "true"}:
            raise ValueError("APP_AI_EXECUTION_ENABLED musi mieć wartość 0/1 lub false/true.")
        schema_format = os.getenv("APP_AI_SCHEMA_FORMAT", "nested").strip().lower()
        if schema_format not in {"nested", "legacy"}:
            raise ValueError("APP_AI_SCHEMA_FORMAT musi mieć wartość nested lub legacy.")
        config = cls(
            execution_enabled=execution in {"1", "true"},
            schema_in_response_format=schema_format == "nested",
            binary=Path(os.getenv("APP_AI_BINARY", str(defaults.binary))).expanduser(),
            model=Path(os.getenv("APP_AI_MODEL", str(defaults.model))).expanduser(),
            port=int(os.getenv("APP_AI_PORT", str(defaults.port))),
            context_size=int(os.getenv("APP_AI_CONTEXT", str(defaults.context_size))),
            threads=int(os.getenv("APP_AI_THREADS", str(defaults.threads))),
            timeout_s=float(os.getenv("APP_AI_TIMEOUT", str(defaults.timeout_s))),
            runs_dir=defaults.runs_dir,
        )
        if not 1024 <= config.port <= 65535 or not 1 <= config.threads <= 4:
            raise ValueError("Nieprawidłowy port lub liczba wątków asystenta.")
        if not 1024 <= config.context_size <= 2048 or not 1 <= config.timeout_s <= 600:
            raise ValueError("Nieprawidłowy kontekst lub timeout asystenta.")
        return config

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"
