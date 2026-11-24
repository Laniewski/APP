"""Hardware-free interactive client for the model-driven assistant."""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from modules.measurement_assistant.backend import LLMBackend
from modules.measurement_assistant.plan_schema import PlanValidator
from modules.measurement_assistant.prompt_loader import load_messages
from modules.measurement_assistant.script_builder import ScriptBuilder


def run_one(backend, request, output_root=None):
    result = backend.generate(load_messages(request), status=print)
    validation = PlanValidator().validate(result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print('Validation:', validation.status, validation.errors)
    print('Metrics:', backend.last_metrics)
    if output_root:
        print(ScriptBuilder().save(output_root, request, result,
              llm_response=backend.last_raw_response, metrics=backend.last_metrics,
              validation=validation, execution_enabled=False))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('request', nargs='*')
    parser.add_argument('--no-save', action='store_true')
    parser.add_argument('--output-dir', type=Path, default=REPO_ROOT / 'local_ai_tests')
    args = parser.parse_args()
    backend = LLMBackend()
    if backend.config.execution_enabled:
        raise SystemExit('APP_AI_EXECUTION_ENABLED musi być 0.')
    try:
        if args.request:
            run_one(backend, ' '.join(args.request), None if args.no_save else args.output_dir)
        else:
            while True:
                try: request = input('> ').strip()
                except EOFError: break
                if not request: break
                run_one(backend, request, None if args.no_save else args.output_dir)
    finally:
        backend.shutdown()


if __name__ == '__main__':
    main()
