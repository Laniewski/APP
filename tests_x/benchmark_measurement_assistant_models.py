#!/usr/bin/env python3
"""Entry point for the source-grounded paired benchmark.

Historical files in benchmark_results remain immutable. Run --mode before,
--mode after or --mode no_examples with an already running local server on
18767. No downloads or hardware execution. See redesign/report.md.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests_x.benchmark_assistant_grounding import main, score

P = 'set_piezo_voltage'
A = 'set_polarization_angle'
T = 'set_temperature'
CASES = [
    ('Ustaw piezo na 12 V.', [(P, {'value_v': 12})]),
    ('Ustaw piezo.', [(P, {'value_v': None})]),
    ('Ustaw drugą łopatkę na 30 stopni.', [(A, {'paddle': 2, 'angle_deg': 30})]),
    ('Ustaw drugą łopatkę.', [(A, {'paddle': 2, 'angle_deg': None})]),
    ('Ustaw temperaturę na 37 stopni i rozpocznij pomiar.', [(T, {'value_c': 37}), ('start_measurement', {})]),
    ('Poczekaj 4 sekundy i zatrzymaj pomiar.', [('wait', {'seconds': 4}), ('stop_measurement', {})]),
    ('Ustaw piezo na 20 V i drugą łopatkę na 45 stopni.', [(P, {'value_v': 20}), (A, {'paddle': 2, 'angle_deg': 45})]),
    ('Ustaw temperaturę.', [(T, {'value_c': None})]),
    ('Rozpocznij pomiar.', [('start_measurement', {})]),
    ('Ustaw pierwszą łopatkę na 25 stopni, potem drugą na 50 stopni.', [(A, {'paddle': 1, 'angle_deg': 25}), (A, {'paddle': 2, 'angle_deg': 50})]),
    ('Ustaw płytkę piezo na 15 V.', [(P, {'value_v': 15})]),
    ('Ustaw drugi nastawnik polaryzacji na 40 stopni.', [(A, {'paddle': 2, 'angle_deg': 40})]),
    ('Najpierw rozpocznij pomiar, potem ustaw piezo na 10 V.', [('start_measurement', {}), (P, {'value_v': 10})]),
    ('Ustaw piezo na 10.', None),
    ('Ustaw drugą łopatkę na dziewięćdziesiąt stopni.', [(A, {'paddle': 2, 'angle_deg': 90})]),
]


def evaluate(plan, expected, missing_questions=None):
    """Compatibility with historical callers; occurrence order now matters."""
    if expected is None:
        return dict(correct_actions=None, correct_order=None, correct_parameters=None,
                    missing_detected=None, hallucinated_parameter=None, full_plan_success=None)
    status = 'INCOMPLETE' if any(v is None for _, a in expected for v in a.values()) else 'COMPLETE'
    result = score(plan, expected, status)
    actual = [(s.get('action'), s.get('args')) for s in plan.get('steps', []) if isinstance(s, dict)]
    return dict(correct_actions=result['action_recognition_accuracy'] == 1 and len(actual) == len(expected),
                correct_order=result['action_order_accuracy'], correct_parameters=actual == expected,
                missing_detected=None if result['missing_argument_accuracy'] is None else result['missing_argument_accuracy'] == 1,
                hallucinated_parameter=bool(result['hallucinated_parameter_rate']))


if __name__ == '__main__':
    main()
