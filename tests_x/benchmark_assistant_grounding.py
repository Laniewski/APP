"""Hardware-free paired benchmark. No nearest-value matching of repeated actions.

Rates with zero denominator are null, never a fabricated perfect score.
Raw model extraction and final deterministic semantics are reported separately.
"""
import argparse
import hashlib
from collections import Counter
import json
from pathlib import Path
import statistics
import sys
import time
import urllib.request
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests_x.assistant_cases import CASES, HOLDOUT
from modules.measurement_assistant.backend import LLMBackend
from modules.measurement_assistant.config import AssistantConfig
from modules.measurement_assistant.plan_schema import PlanValidator, parse_response


def score(plan, expected, status, valid_json=True):
    steps = plan.get('steps', []) if isinstance(plan, dict) else []
    actual = [(s.get('action'), s.get('args', {})) for s in steps if isinstance(s, dict)]
    names, wanted = [a for a, _ in actual], [a for a, _ in expected]
    overlap = sum((Counter(names) & Counter(wanted)).values())
    args_total = sum(len(args) for _, args in expected)
    args_ok = missing_ok = missing_total = unsupported_ok = unsupported_fp = hallucinated_params = 0
    for i, (action, args) in enumerate(expected):
        got_action, got_args = actual[i] if i < len(actual) else (None, {})
        got_args = got_args if isinstance(got_args, dict) else {}
        unsupported_ok += action == 'unsupported' and got_action == action
        for key, value in args.items():
            correct = got_action == action and key in got_args and type(got_args[key]) is not bool and got_args[key] == value
            args_ok += correct
            if value is None:
                missing_total += 1
                missing_ok += correct
    for i, (action, args) in enumerate(actual):
        target, target_args = expected[i] if i < len(expected) else (None, {})
        unsupported_fp += action == 'unsupported' and target != action
        if isinstance(args, dict):
            hallucinated_params += sum(v is not None and (target != action or k not in target_args or v != target_args[k] or isinstance(v, bool)) for k, v in args.items())
    expected_status = 'INVALID' if 'unsupported' in wanted else 'INCOMPLETE' if missing_total else 'COMPLETE'
    ratio = lambda n, d: n / d if d else None
    return {
        'action_recognition_accuracy': ratio(overlap, len(expected)),
        'action_order_accuracy': names == wanted,
        'argument_binding_accuracy': ratio(args_ok, args_total),
        'missing_argument_accuracy': ratio(missing_ok, missing_total),
        'unsupported_action_recall': ratio(unsupported_ok, wanted.count('unsupported')),
        'unsupported_action_false_positive_rate': ratio(unsupported_fp, sum(a != 'unsupported' for a in wanted)),
        'hallucinated_action_rate': ratio(sum((Counter(names) - Counter(wanted)).values()), len(actual)),
        'hallucinated_parameter_rate': ratio(hallucinated_params, sum(len(a) for _, a in actual if isinstance(a, dict))),
        'dropped_requested_action_rate': ratio(sum((Counter(wanted) - Counter(names)).values()), len(expected)),
        'json_validity': valid_json, 'status_correct': status == expected_status,
        'full_semantic_plan_success': valid_json and actual == expected and status == expected_status,
    }


def post(path, payload):
    req = urllib.request.Request('http://127.0.0.1:18767' + path, data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=180) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', default='', help='Output suffix for a new revision, preserving previous runs')
    parser.add_argument('--cases', help='Comma-separated acceptance ids for a targeted recheck')
    parser.add_argument('--holdout', action='store_true')
    parser.add_argument('--mode', choices=['before', 'after', 'no_examples'], required=True)
    args = parser.parse_args()
    root = Path('benchmark_results/redesign')
    baseline = json.loads((root / 'baseline_contract.json').read_text())
    backend = LLMBackend(AssistantConfig(port=18767, timeout_s=180))
    from modules.measurement_assistant.context_builder import system_prompt, extraction_schema
    contract = {'prompt': system_prompt(), 'schema': extraction_schema(), 'context_size': 2048,
                'threads': 3, 'temperature': 0, 'max_tokens_per_request': 400,
                'source_hashes': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in Path('modules/measurement_assistant').glob('*.py')}}
    if args.mode == 'after':
        (root / ('after' + args.label + ('_recheck' if args.cases else '') + '_contract.json')).write_text(json.dumps(contract, ensure_ascii=False, indent=2))
    rows = []
    cases = (HOLDOUT if args.holdout else CASES) if args.mode != 'no_examples' else [CASES[i] for i in (2, 7, 11)]
    if args.cases:
        cases = [c for c in cases if c[0] in args.cases.split(',')]
    for name, request, expected in cases:
        print(args.mode, name, flush=True)
        started = time.monotonic()
        row = {'case': name, 'request': request, 'expected': expected}
        plan, valid = {}, False
        try:
            if args.mode == 'after':
                plan = backend.generate(request)
                row.update(raw=backend.last_raw_response, metrics=backend.last_metrics)
                valid = True
            else:
                prompt = baseline['prompt']
                if args.mode == 'no_examples':
                    prompt = prompt.split('\nPrzykłady')[0]
                response = post('/v1/chat/completions', {'messages': [{'role': 'system', 'content': prompt}, {'role': 'user', 'content': request}], 'temperature': 0, 'max_tokens': 400, 'response_format': {'type': 'json_object', 'schema': baseline['schema']}})
                row['response'] = response
                row['metrics'] = {**response.get('usage', {}), 'timings': response.get('timings', {})}
                plan = parse_response(response['choices'][0]['message']['content'])
                valid = True
            validation = PlanValidator().validate(plan)
            row['status'] = validation.status
            row['validation_errors'] = validation.errors
            # Unsupported is a semantically invalid plan, not malformed JSON/schema.
            row['schema_validity'] = not any('nieobsługiwana' not in e for e in validation.errors)
        except Exception as exc:
            row['error'] = str(exc)
            if args.mode == 'after':
                row.update(raw=backend.last_raw_response, metrics=backend.last_metrics)
            row['status'] = 'ERROR'
            row['schema_validity'] = False
        if args.mode == 'after' and backend.last_metrics.get('extracted_steps') is not None:
            raw_steps = backend.last_metrics['extracted_steps']
            raw_plan = {'steps': raw_steps}
            raw_status = 'INVALID' if any(s['action'] == 'unsupported' for s in raw_steps) else 'INCOMPLETE' if any(v is None for s in raw_steps for v in s['args'].values()) else 'COMPLETE'
            row['raw_score'] = score(raw_plan, expected, raw_status)
        row.update(plan=plan, elapsed_s=time.monotonic()-started)
        row.update(score(plan, expected, row['status'], valid))
        metrics = row.get('metrics', {})
        row['prompt_tokens'] = metrics.get('prompt_tokens')
        row['output_tokens'] = metrics.get('completion_tokens')
        row['tokens_per_s'] = metrics.get('tokens_per_s', metrics.get('timings', {}).get('predicted_per_second'))
        rows.append(row)
        keys = list(score({}, [], 'ERROR')) + ['schema_validity', 'elapsed_s', 'prompt_tokens', 'output_tokens', 'tokens_per_s']
        summary = {k: statistics.mean([float(r[k]) for r in rows if r.get(k) is not None]) if any(r.get(k) is not None for r in rows) else None for k in keys}
        (root / (args.mode + args.label + ('_holdout' if args.holdout else '') + ('_recheck' if args.cases else '') + '.json')).write_text(json.dumps({'mode': args.mode, 'summary': summary, 'tests': rows}, ensure_ascii=False, indent=2))
        print(name, row['status'], row['full_semantic_plan_success'], round(row['elapsed_s'], 2), flush=True)


if __name__ == '__main__':
    main()
