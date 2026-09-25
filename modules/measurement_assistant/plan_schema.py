"""Niezależna walidacja; żadne deklaracje modelu nie nadają uprawnień."""

import json
import math
from dataclasses import dataclass

from .actions import ACTION_REGISTRY


@dataclass(frozen=True)
class ValidationResult:
    errors: tuple[str, ...]
    missing_parameters: tuple[str, ...]

    @property
    def structurally_valid(self):
        return not self.errors

    @property
    def status(self):
        if self.errors:
            return "INVALID"
        return "INCOMPLETE" if self.missing_parameters else "COMPLETE"

    @property
    def runnable(self):
        return self.status == "COMPLETE"


def parse_response(text):
    if not isinstance(text, str) or len(text) > 100000:
        raise ValueError("Nieprawidłowy rozmiar odpowiedzi modelu.")
    def no_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Powtórzone pole JSON: {key}")
            result[key] = value
        return result
    result = json.loads(text, object_pairs_hook=no_duplicates,
                        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    if not isinstance(result, dict):
        raise ValueError("Plan musi być obiektem JSON.")
    return result


class PlanValidator:
    def validate(self, plan, request=None):
        errors = []
        derived_missing = []
        if not isinstance(plan, dict):
            return ValidationResult(("Plan musi być obiektem.",), ())
        expected = {"title", "steps", "missing_parameters", "notes"}
        if set(plan) != expected:
            errors.append("Wymagane są wyłącznie pola title, steps, missing_parameters, notes.")
        if not isinstance(plan.get("title"), str) or not plan.get("title", "").strip():
            errors.append("Brak tytułu planu.")
        for name in ("missing_parameters", "notes"):
            if not isinstance(plan.get(name), list) or not all(isinstance(item, str) for item in plan.get(name, [])):
                errors.append(f"{name} musi być listą tekstów.")
        steps = plan.get("steps")
        if not isinstance(steps, list) or not 0 <= len(steps) <= 100:
            errors.append("Plan musi zawierać od 0 do 100 kroków.")
            steps = []
        if isinstance(plan.get("steps"), list) and not steps:
            derived_missing.append("Podaj co najmniej jedną obsługiwaną akcję.")
        for number, step in enumerate(steps, 1):
            if not isinstance(step, dict) or set(step) != {"description", "action", "args"}:
                errors.append(f"Krok {number}: nieprawidłowe pola.")
                continue
            if not isinstance(step["description"], str):
                errors.append(f"Krok {number}: description musi być tekstem.")
            name = step["action"]
            spec = ACTION_REGISTRY.get(name) if isinstance(name, str) else None
            if spec is None:
                errors.append(f"Krok {number}: nieznana akcja {name!r}.")
                continue
            args = step["args"]
            required = {key for key, arg in spec.arguments.items() if arg.required}
            if not isinstance(args, dict) or not required <= set(args) or not set(args) <= set(spec.arguments):
                errors.append(f"Krok {number}: wymagane argumenty: {sorted(required)}; nie wolno dodawać innych.")
                continue
            for key, arg_spec in spec.arguments.items():
                if key not in args:
                    continue
                value = args[key]
                if value is None:
                    if not arg_spec.nullable:
                        errors.append(f"Krok {number}: {key} nie dopuszcza null.")
                    elif arg_spec.required:
                        derived_missing.append(f"Krok {number}: {spec.missing_question(key, args)}")
                    continue
                numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
                try:
                    finite = numeric and math.isfinite(value)
                except OverflowError:
                    finite = False
                if not finite or (arg_spec.kind == "integer" and not isinstance(value, int)):
                    errors.append(f"Krok {number}: {key} ma niewłaściwy typ.")
                elif (arg_spec.minimum is not None and value < arg_spec.minimum
                      or arg_spec.maximum is not None and value > arg_spec.maximum
                      or arg_spec.choices and value not in arg_spec.choices):
                    errors.append(f"Krok {number}: {key} poza dozwolonym zakresem.")
        missing = plan.get("missing_parameters", [])
        missing = derived_missing + (list(missing) if isinstance(missing, list) and all(isinstance(x, str) for x in missing) else [])
        if requires_unsupported_stabilization(request):
            missing.append(STABILIZATION_MISSING)
        return ValidationResult(tuple(errors), tuple(dict.fromkeys(missing)))


STABILIZATION_MISSING = (
    "Podaj tolerancję temperatury i czas stabilności. Akcja wykrywania stabilizacji "
    "nie jest jeszcze dostępna; zwykłe wait nie może jej zastąpić."
)


def requires_unsupported_stabilization(request):
    """Konserwatywna blokada znanej, nieobsługiwanej intencji — nie parser procedur."""
    if not isinstance(request, str):
        return False
    text = request.casefold()
    return any(word in text for word in ("stabil", "stable", "steady state"))


def response_schema():
    variants = []
    for spec in ACTION_REGISTRY.values():
        variants.append({
            "type": "object", "additionalProperties": False,
            "required": ["description", "action", "args"],
            "properties": {
                "description": {"type": "string"},
                "action": {"type": "string", "const": spec.name},
                "args": {"type": "object", "additionalProperties": False,
                         "required": [key for key, arg in spec.arguments.items() if arg.required],
                         "properties": {key: arg.schema() for key, arg in spec.arguments.items()}},
            },
        })
    return {
        "type": "object", "additionalProperties": False,
        "required": ["title", "steps", "missing_parameters", "notes"],
        "properties": {
            "title": {"type": "string"},
            "steps": {"type": "array", "minItems": 0, "maxItems": 100,
                      "items": {"oneOf": variants}},
            "missing_parameters": {"type": "array", "items": {"type": "string"}},
            "notes": {"type": "array", "items": {"type": "string"}},
        },
    }
