"""Acceptance checks for the hardware-free Windows planning path."""

import unittest
import tempfile
from pathlib import Path

from modules.measurement_assistant.config import AssistantConfig
from modules.measurement_assistant.grounding import grounded_plan
from modules.measurement_assistant.plan_schema import PlanValidator
from tools.ai_plan_tester import save_result


CASES = [
    ("Ustaw piezo na 12 V.", "COMPLETE"),
    ("Ustaw piezo.", "INCOMPLETE"),
    ("Ustaw drugą łopatkę.", "INCOMPLETE"),
    ("Ustaw drugą łopatkę na 30 stopni.", "COMPLETE"),
    ("Ustaw temperaturę na 37 stopni i rozpocznij pomiar.", "COMPLETE"),
    ("Włącz grzałkę.", "INVALID"),
    ("wlacz grzalke", "INVALID"),
    ("Zapisz plik.", "INVALID"),
    ("Ustaw piezo na 50 V i włącz grzałkę.", "INVALID"),
    ("Ustaw łopatkę 1, potem piezo na 50 V, potem łopatki na 100.", "INCOMPLETE"),
    ("ustaw temerature na 20 stopni", "COMPLETE"),
    ("zakoncz pomiar", "COMPLETE"),
]


class PcOnlyTests(unittest.TestCase):
    def test_requested_acceptance_cases(self):
        for request, status in CASES:
            with self.subTest(request=request):
                plan = grounded_plan(request)
                self.assertEqual(PlanValidator().validate(plan, request).status, status)

    def test_execution_gate_is_disabled_by_default(self):
        config = AssistantConfig.from_env()
        self.assertFalse(config.execution_enabled)

    def test_result_bundle_contains_requested_files(self):
        request = "Ustaw piezo na 12 V."
        plan = grounded_plan(request)
        validation = PlanValidator().validate(plan, request)
        with tempfile.TemporaryDirectory() as root:
            directory = save_result(Path(root), request, [(0, 19, "Ustaw piezo na 12 V")],
                                    {"steps": []}, plan, {"requests": 1}, validation)
            self.assertEqual({path.name for path in directory.iterdir()}, {
                "request.txt", "segments.json", "model_extraction.json",
                "final_plan.json", "metrics.json",
            })


if __name__ == "__main__":
    unittest.main()
