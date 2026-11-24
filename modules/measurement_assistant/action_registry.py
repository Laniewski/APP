"""Pure planning contract shared by the AI layer and hardware execution.

This module deliberately has no Qt, serial, or device-driver imports so planning
and validation can run on a workstation without the laboratory hardware stack.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ArgumentSpec:
    kind: str
    description: str
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple = ()
    required: bool = True
    nullable: bool = True
    unit: str | None = None
    aliases: tuple[str, ...] = ()
    choice_aliases: dict = field(default_factory=dict)
    explicit_value: bool = True
    question: str = "Podaj wartość parametru."
    question_variants: dict = field(default_factory=dict)

    def schema(self):
        result = {"type": [self.kind, "null"] if self.nullable else self.kind,
                  "description": self.description}
        if self.minimum is not None:
            result["minimum"] = self.minimum
        if self.maximum is not None:
            result["maximum"] = self.maximum
        if self.choices:
            result["enum"] = list(self.choices) + ([None] if self.nullable else [])
        return result

    def tool_definition(self):
        result = self.schema()
        result.update(required=self.required, explicit_value=self.explicit_value)
        if self.unit:
            result["unit"] = self.unit
        if self.aliases:
            result["aliases"] = list(self.aliases)
        if self.choice_aliases:
            result["choice_aliases"] = self.choice_aliases
        return result


@dataclass(frozen=True)
class ActionSpec:
    name: str
    description: str
    arguments: dict[str, ArgumentSpec] = field(default_factory=dict)
    aliases: tuple[str, ...] = ()

    def tool_definition(self):
        return {"name": self.name, "description": self.description,
                "aliases": list(self.aliases),
                "arguments": {key: arg.tool_definition() for key, arg in self.arguments.items()}}

    def missing_question(self, key, args):
        argument = self.arguments[key]
        for selector, questions in argument.question_variants.items():
            try:
                question = questions.get(args.get(selector))
            except TypeError:
                question = None
            if question:
                return question
        return argument.question


# Semantic data and bounds live exclusively in ai_context.
from .prompt_loader import load_json

# Code-owned allowlist: editing context files cannot grant execution capabilities.
EXECUTABLE_ACTIONS = frozenset({
    "set_temperature", "heater_on", "heater_off", "set_piezo_voltage",
    "set_polarization_angle", "move_polarization", "start_measurement",
    "stop_measurement", "wait",
})


def action_definitions():
    station = load_json("station_and_actions.json")
    actions = [a for device in station["devices"] for a in device["actions"]]
    actions += station["general_actions"]
    return {a["name"]: a for a in actions}


ACTION_REGISTRY = {
    name: ActionSpec(name, action["description"], {
        key: ArgumentSpec(kind=arg["type"], description=arg["description"],
                          minimum=arg.get("minimum"), maximum=arg.get("maximum"),
                          choices=tuple(arg.get("choices", [])), required=arg["required"],
                          nullable=False, unit=arg.get("unit"), question=arg["missing_error"])
        for key, arg in action["arguments"].items()
    }) for name, action in action_definitions().items()
}
