"""Kontekst planowania z rejestru narzędzi; bez stanu sprzętu i historii."""

import json

from .actions import ACTION_REGISTRY


def tool_definitions():
    return [spec.tool_definition() for spec in ACTION_REGISTRY.values()]


def planning_examples():
    return [
        ("Ustaw piezo na 20 V.", [("set_piezo_voltage", {"value_v": 20})]),
        ("Ustaw piezo.", [("set_piezo_voltage", {"value_v": None})]),
        ("Ustaw drugą łopatkę na 35 stopni.", [("set_polarization_angle", {"paddle": 2, "angle_deg": 35})]),
        ("Ustaw drugą łopatkę.", [("set_polarization_angle", {"paddle": 2, "angle_deg": None})]),
        ("Ustaw temperaturę na 37 stopni i rozpocznij pomiar.",
         [("set_temperature", {"value_c": 37}), ("start_measurement", {})]),
    ]


def system_prompt():
    rules = (
        "Jesteś planerem procedur laboratoryjnych. Zwróć tylko obiekt JSON: title (tekst), "
        "steps (lista {description, action, args}), missing_parameters (lista tekstów), notes (lista tekstów). "
        "Opisy po polsku. Używaj wyłącznie zdefiniowanych akcji. Nie generuj Python ani shell. "
        "Zachowuj operacje i kolejność z bieżącego polecenia użytkownika. "
        "Nigdy nie wymyślaj wartości: każdy argument musi pochodzić jawnie z bieżącego polecenia; "
        "liczby słowne i numery porządkowe są jawnymi wartościami. "
        "Zachowaj rozpoznaną akcję nawet przy braku danych: brakujący wymagany argument zwróć jako null. "
        "Nie pomijaj niekompletnej akcji. Null oznacza brak danych, nigdy zero ani wartość domyślną. "
        "Wartości przykładów i ograniczenia narzędzi NIE są wartościami domyślnymi. "
        "missing_parameters pozostaw []; aplikacja wyznaczy pytania z null. "
        "Wyjątek: nieobsługiwane operacje opisz w missing_parameters. "
        "Nie decyduj, że plan jest runnable. Sprzęt musi być wcześniej podłączony ręcznie. "
        "Nie zgaduj jednostek; niejasność zgłoś pytaniem w missing_parameters. "
        "Stabilizacja temperatury jest nieobsługiwana; zgłoś ją w missing_parameters, "
        "nigdy nie zastępuj jej wymyślonym wait.\n"
    )
    tools = json.dumps(tool_definitions(), ensure_ascii=False, separators=(",", ":"))
    examples = [{"input": text, "steps": [{"action": action, "args": args} for action, args in actions]}
                for text, actions in planning_examples()]
    contrasts = [
        {"input": "Ustaw drugą łopatkę.", "bad": {"angle_deg": 90},
         "why": "Użytkownik nie podał kąta.", "correct": {"angle_deg": None}},
        {"input": "Ustaw piezo.", "bad": {"value_v": 0},
         "why": "Użytkownik nie podał 0 V.", "correct": {"value_v": None}},
    ]
    return (rules + "Narzędzia: " + tools + "\nPrzykłady kroków (dodaj description oraz pola planu): "
            + json.dumps(examples, ensure_ascii=False, separators=(",", ":"))
            + "\nAntyprzykłady: " + json.dumps(contrasts, ensure_ascii=False, separators=(",", ":")))
