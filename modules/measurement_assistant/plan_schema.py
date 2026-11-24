"""Niezależna walidacja; żadne deklaracje modelu nie nadają uprawnień."""

import json
import math
from dataclasses import dataclass

from .action_registry import action_definitions, EXECUTABLE_ACTIONS
from .prompt_loader import load_json


@dataclass(frozen=True)
class ValidationResult:
    errors: tuple[str, ...]
    missing_parameters: tuple[str, ...]

    response_type: str = "procedure"

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
        return self.response_type == "procedure" and self.status == "COMPLETE"


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


def _matches_type(value, kind):
    if isinstance(kind, list):
        return any(_matches_type(value, k) for k in kind)
    if kind in ("number", "integer"):
        try:
            return type(value) in ((int,) if kind == "integer" else (int, float)) and math.isfinite(value)
        except OverflowError:
            return False
    return {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}.get(kind) is type(value)


def _check(value, schema, path="$"):
    """Technical subset used by output_schema.json; never examines user language."""
    if "oneOf" in schema:
        matches = [not _check(value, variant, path) for variant in schema["oneOf"]]
        return [] if sum(matches) == 1 else [f"{path}: struktura nie pasuje do dokładnie jednego wariantu schema."]
    if "type" in schema and not _matches_type(value, schema["type"]):
        return [f"{path}: niewłaściwy typ."]
    errors = []
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: niewłaściwa wartość stała.")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: wartość spoza choices.")
    if type(value) in (int, float):
        if value < schema.get("minimum", -math.inf) or value > schema.get("maximum", math.inf):
            errors.append(f"{path}: wartość poza zakresem.")
    if isinstance(value, str) and len(value.strip()) < schema.get("minLength", 0):
        errors.append(f"{path}: pusty tekst.")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: brak {key}.")
        if schema.get("additionalProperties") is False and set(value) - set(props):
            errors.append(f"{path}: nieznane pola.")
        for key in set(value) & set(props):
            errors.extend(_check(value[key], props[key], f"{path}.{key}"))
    if isinstance(value, list):
        if not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", math.inf):
            errors.append(f"{path}: niewłaściwa liczba elementów.")
        for i, item in enumerate(value):
            errors.extend(_check(item, schema.get("items", {}), f"{path}[{i}]"))
    return errors


class PlanValidator:
    def validate(self, plan, request=None):
        # request retained only for callers' compatibility; never interpreted.
        kind = plan.get("type") if isinstance(plan, dict) else None
        errors = _check(plan, response_schema(), "$")
        missing = []
        if kind == "procedure" and isinstance(plan.get("steps"), list):
            definitions = action_definitions()
            for index, step in enumerate(plan["steps"], 1):
                if not isinstance(step, dict):
                    continue
                name = step.get("action")
                spec = definitions.get(name) if isinstance(name, str) else None
                if spec is None:
                    errors.append(f"Krok {index}: nieznana akcja.")
                    continue
                if not spec.get("executable") or name not in EXECUTABLE_ACTIONS:
                    errors.append(f"Krok {index}: {name} nie ma dostępnego adaptera wykonawczego.")
                args = step.get("args")
                if not isinstance(args, dict):
                    continue
                if set(args) - set(spec["arguments"]):
                    errors.append(f"Krok {index}: nieznane argumenty.")
                for key, arg in spec["arguments"].items():
                    if key not in args:
                        if arg["required"]:
                            missing.append(arg["missing_error"])
                            errors.append(f"Krok {index}: brak {key}.")
                        continue
                    rules = {k: arg[k] for k in ("type", "minimum", "maximum") if k in arg}
                    if "choices" in arg:
                        rules["enum"] = arg["choices"]
                    errors.extend(_check(args[key], rules, f"Krok {index}.{key}"))
        return ValidationResult(tuple(errors), tuple(missing), kind)


def response_schema():
    return load_json("output_schema.json")
