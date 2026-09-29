"""Interactive, hardware-free tester for the measurement assistant planner."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from modules.measurement_assistant.backend import LLMBackend
from modules.measurement_assistant.grounding import segments
from modules.measurement_assistant.plan_schema import PlanValidator, parse_response


def pretty(value):
    return json.dumps(value, ensure_ascii=False, indent=2)


def parsed_responses(raw):
    if raw is None:
        return []
    try:
        responses = json.loads(raw)
        return [parse_response(item) for item in responses]
    except (TypeError, ValueError, json.JSONDecodeError):
        return {"raw": raw, "parse_error": "Nie udało się sparsować zapisanej odpowiedzi modelu."}


def unsupported_actions(plan):
    return [step["description"] for step in plan.get("steps", [])
            if isinstance(step, dict) and step.get("action") == "unsupported"]


def save_result(root, request, spans, extraction, plan, metrics, validation):
    root.mkdir(parents=True, exist_ok=True)
    directory = root / datetime.now().strftime("%Y-%m-%d_%H%M%S")
    suffix = 1
    while directory.exists():
        directory = root / f"{datetime.now():%Y-%m-%d_%H%M%S}_{suffix:02d}"
        suffix += 1
    directory.mkdir()
    files = {
        "request.txt": request,
        "segments.json": pretty([{"id": i, "start": start, "end": end, "text": text}
                                  for i, (start, end, text) in enumerate(spans)]),
        "model_extraction.json": pretty(extraction),
        "final_plan.json": pretty(plan),
        "metrics.json": pretty({**metrics, "status": validation.status,
                                  "validation_errors": list(validation.errors),
                                  "missing_arguments": list(validation.missing_parameters),
                                  "unsupported_actions": unsupported_actions(plan)}),
    }
    for name, content in files.items():
        (directory / name).write_text(content, encoding="utf-8")
    return directory


def run_one(backend, request, output_root=None):
    spans = segments(request)
    print("\n1. INPUT\n" + request)
    print("\n2. SEGMENTS")
    for index, (_, _, text) in enumerate(spans):
        print(f'[{index}] {text.strip()!r}')

    plan = backend.generate(request, status=lambda message: print(f"[llama.cpp] {message}"))
    extraction = {
        "raw_responses": json.loads(backend.last_raw_response or "[]"),
        "parsed_responses": parsed_responses(backend.last_raw_response),
        "steps": backend.last_model_extraction,
        "agrees_with_grounding": backend.last_metrics.get("model_agrees"),
    }
    validation = PlanValidator().validate(plan, request)
    final_plan = dict(plan)
    final_plan["missing_parameters"] = list(validation.missing_parameters)

    print("\n3. MODEL EXTRACTION\n" + pretty(extraction))
    print("\n4. GROUNDED PLAN\n" + pretty(plan))
    print("\n5. VALIDATION RESULT")
    print(pretty({"errors": list(validation.errors),
                  "missing_arguments": list(validation.missing_parameters),
                  "unsupported_actions": unsupported_actions(plan)}))
    print("\n6. STATUS:\n" + validation.status)
    print("\n7. FINAL JSON\n" + pretty(final_plan))
    metrics = dict(backend.last_metrics)
    print("\n8. METRICS")
    print(pretty({key: metrics.get(key) for key in
                  ("elapsed_s", "prompt_tokens", "completion_tokens", "tokens_per_s", "requests")}))
    if output_root is not None:
        directory = save_result(output_root, request, spans, extraction, final_plan, metrics, validation)
        print(f"\nZapisano: {directory}")


def main():
    parser = argparse.ArgumentParser(description="PC-only tester planowania AI (bez wykonania sprzętowego).")
    parser.add_argument("request", nargs="*", help="Jedno polecenie; bez niego uruchamia się tryb interaktywny.")
    parser.add_argument("--no-save", action="store_true", help="Nie zapisuj artefaktów w local_ai_tests.")
    parser.add_argument("--output-dir", type=Path, default=REPO_ROOT / "local_ai_tests")
    args = parser.parse_args()

    backend = LLMBackend()
    if backend.config.execution_enabled:
        raise SystemExit("APP_AI_EXECUTION_ENABLED musi mieć wartość 0 w testerze PC-only.")
    output_root = None if args.no_save else args.output_dir
    try:
        if args.request:
            run_one(backend, " ".join(args.request), output_root)
            return
        print("Tester PC-only. Pusta linia kończy pracę. Wykonanie sprzętowe: WYŁĄCZONE.")
        while True:
            try:
                request = input("\nPodaj polecenie:\n> ").strip()
            except EOFError:
                break
            if not request:
                break
            try:
                run_one(backend, request, output_root)
            except Exception as exc:
                print(f"\nSTATUS: INVALID\nBłąd: {exc}", file=sys.stderr)
    finally:
        backend.shutdown()


if __name__ == "__main__":
    main()
