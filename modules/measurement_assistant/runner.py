"""Runner importuje wyłącznie kod zgodny z deterministycznym ScriptBuilderem."""

import importlib.abc
import importlib.util
import logging
import threading
from pathlib import Path

from .actions import ActionStopped
from .config import AssistantConfig
from .script_builder import ScriptBuilder

logger = logging.getLogger(__name__)


class _VerifiedLoader(importlib.abc.SourceLoader):
    def __init__(self, path, data):
        self.path, self.data = str(path), data

    def get_filename(self, fullname):
        return self.path

    def get_data(self, path):
        if path != self.path:
            raise OSError("Odczyt innego pliku jest niedozwolony.")
        return self.data


class Runner:
    def __init__(self, config=None):
        self.config = config or AssistantConfig.from_env()

    def run(self, script_path, plan, actions, stop_event=None):
        if not self.config.execution_enabled or not getattr(actions, "execution_enabled", True):
            raise RuntimeError("Tryb wykonania AI jest wyłączony.")
        stop_event = stop_event or threading.Event()
        path = Path(script_path)
        expected = ScriptBuilder().build(plan).encode("utf-8")
        if path.is_symlink() or path.read_bytes() != expected:
            raise ValueError("script.py został zmieniony; ponownie utwórz plan.")
        loader = _VerifiedLoader(path, expected)
        spec = importlib.util.spec_from_loader("app_v2_generated_procedure", loader)
        module = importlib.util.module_from_spec(spec)
        handler = logging.FileHandler(path.parent / "run.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        loggers = [logger, logging.getLogger("modules.measurement_assistant.actions")]
        for target in loggers:
            target.addHandler(handler)
        try:
            if hasattr(actions, "prepare"):
                actions.prepare(stop_event)
            loader.exec_module(module)
            logger.info("Rozpoczęcie procedury.")
            module.run(actions, stop_event)
            logger.info("Procedura %s.", "zatrzymana" if stop_event.is_set() else "zakończona")
            return not stop_event.is_set()
        except ActionStopped:
            logger.info("Procedura zatrzymana.")
            return False
        except Exception:
            if hasattr(actions, "cancel"):
                actions.cancel()
            logger.exception("Błąd procedury.")
            raise
        finally:
            for target in loggers:
                target.removeHandler(handler)
            handler.close()
