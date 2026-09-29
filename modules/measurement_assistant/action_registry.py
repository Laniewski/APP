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


# Keep these limits aligned with the existing TC200 and MPC220 drivers. They are
# repeated here to keep the planning contract importable without pyserial/Qt.
ACTION_REGISTRY = {
    spec.name: spec for spec in (
        ActionSpec("set_temperature", "Ustaw temperaturę zadaną TC200; nie włącza grzałki ani nie czeka na stabilizację.", {
            "value_c": ArgumentSpec("number", "Temperatura zadana", 20.0, 200.0,
                                    unit="°C", aliases=("temperatura",), question="Podaj temperaturę zadaną."),
        }, aliases=("temperatura", "temperatura zadana")),
        ActionSpec("set_piezo_voltage", "Ustaw napięcie piezo MDT694B; zakres sprawdza istniejący sterownik.", {
            "value_v": ArgumentSpec("number", "Napięcie piezo", unit="V", aliases=("napięcie",),
                                    question="Podaj napięcie piezo."),
        }, aliases=("piezo", "płytka piezo", "napięcie piezo", "kontroler piezo")),
        ActionSpec("set_polarization_angle", "Ustaw kąt jednej łopatki MPC220 i poczekaj na zakończenie ruchu.", {
            "paddle": ArgumentSpec("integer", "Numer łopatki", choices=(1, 2),
                                   choice_aliases={1: ("pierwsza", "pierwszy"), 2: ("druga", "drugi")},
                                   question="Podaj numer łopatki."),
            "angle_deg": ArgumentSpec("number", "Kąt łopatki", 1.0, 160.0,
                                      unit="stopnie", aliases=("kąt",), question="Podaj kąt łopatki.",
                                      question_variants={"paddle": {1: "Podaj kąt pierwszej łopatki.",
                                                                   2: "Podaj kąt drugiej łopatki."}}),
        }, aliases=("łopatka", "łopatka polaryzacji", "nastawnik polaryzacji", "polaryzacja")),
        ActionSpec("start_measurement", "Rozpocznij ADS1263 z kanałami wybranymi w GUI.", aliases=("rozpocznij pomiar",)),
        ActionSpec("stop_measurement", "Zatrzymaj ADS1263; dane pozostają w buforze.", aliases=("zatrzymaj pomiar",)),
        ActionSpec("wait", "Poczekaj podaną liczbę sekund; nie jest to detekcja stabilizacji.", {
            "seconds": ArgumentSpec("number", "Czas oczekiwania", 0, 3600, unit="s", aliases=("sekundy",),
                                    question="Podaj czas oczekiwania w sekundach."),
        }, aliases=("poczekaj", "odczekaj")),
    )
}
