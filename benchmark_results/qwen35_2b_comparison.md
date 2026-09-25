# Zmiana kontraktu measurement_assistant: null i trzy stany

Gałąź: architecture-v2-learning. Qwen3.5-2B Q4_K_M użyty wyłącznie w benchmarku. Produkcyjny model i config.py pozostają bez zmian. Bez pomiarów fizycznych i komunikacji sprzętowej.

## Pliki i odpowiedzialności

- modules/measurement_assistant/actions.py: metadane wymagania/null/jednostek/pochodzenia wartości, polskie aliasy, serializacja narzędzi i metadane pytań. Część wykonawcza od ActionStopped dalej zachowana identycznie.
- modules/measurement_assistant/context_builder.py (nowy): zwięzłe zasady, definicje narzędzi, 5 krótkich przykładów i 2 kontrastowe antyprzykłady. Bez live-state i historii.
- modules/measurement_assistant/backend.py: import system_prompt z context_builder; zachowany transport HTTP, retry, metrics i blokada stabilizacji. Funkcja system_prompt nadal dostępna pod dotychczasowym importem.
- modules/measurement_assistant/plan_schema.py: nullable schema, steps [] dozwolone strukturalnie; COMPLETE/INCOMPLETE/INVALID; pytania wyznaczane z null. Wymagane klucze nadal wymagane, ale mogą mieć null. Opcjonalny nullable null nie blokuje kompletności. Opcjonalny pominięty klucz dozwolony; nonnullable null jest INVALID. Pusty plan zawsze niewykonywalny.
- tests_x/test_measurement_assistant.py: 42 testy, w tym nowe przypadki null, opcjonalności, stanów, pytań GUI, blokady script.py i punktacji benchmarku. Sprzęt zastępują atrapy.
- tests_x/benchmark_measurement_assistant_models.py: odczyt nowego context_builder przez AST, niezmienione CASES, oczekiwanie zachowanych akcji z null, pytania z wyniku walidatora, raport before/after. Naprawiona obsługa krotek pytań; surowe odpowiedzi bez zmian.
- benchmark_results/qwen35_2b_results.json, qwen35_2b_report.md, qwen35_2b_server.log: nowe wyniki wykonania w dotychczasowych plikach.
- benchmark_results/before_null_contract/: zachowane 3 poprzednie pliki results.json/report.md/server.log pod oryginalnymi nazwami.
- benchmark_results/qwen35_2b_comparison.md (ten plik): podsumowanie zmian, przykłady i ograniczenia.

Hashami potwierdzono brak zmian config.py, controller.py, runner.py, script_builder.py i panel.py względem stanu przed zadaniem. Część MeasurementActions porównano znak po znaku. ScriptBuilder i Runner nadal niezależnie wymagają runnable.

## Przykład ActionSpec

```python
ActionSpec("set_piezo_voltage", "Ustaw napięcie piezo.", {
    "value_v": ArgumentSpec("number", "Napięcie piezo",
        required=True, nullable=True, unit="V", explicit_value=True,
        aliases=("napięcie",), question="Podaj napięcie piezo."),
}, aliases=("piezo", "płytka piezo", "napięcie piezo", "kontroler piezo"))
```

## Przykłady stanów

### COMPLETE

```json
{
  "title": "Ustaw drugą łopatkę na 30 stopni.",
  "steps": [
    {
      "description": "Ustaw kąt jednej łopatki MPC220 i poczekaj na zakończenie ruchu.",
      "action": "set_polarization_angle",
      "args": {
        "paddle": 2,
        "angle_deg": 30
      }
    }
  ],
  "missing_parameters": [],
  "notes": []
}
```

Wszystkie wartości obecne i poprawne; runnable=True.

### INCOMPLETE

```json
{
  "title": "Ustaw piezo.",
  "steps": [
    {
      "description": "Ustaw napięcie piezo MDT694B.",
      "action": "set_piezo_voltage",
      "args": {
        "value_v": null
      }
    }
  ],
  "missing_parameters": [],
  "notes": []
}
```

value_v=null jest strukturalnie poprawne. Walidator generuje „Krok 1: Podaj napięcie piezo.” mimo missing_parameters=[] od modelu. runnable=False, script.py nie powstaje.

### INVALID

```json
{
  "title": "Ustaw drugą łopatkę na 30 stopni.",
  "steps": [
    {
      "description": "Ustaw kąt jednej łopatki MPC220 i poczekaj na zakończenie ruchu.",
      "action": "set_polarization_angle",
      "args": {
        "paddle": 2,
        "angle_deg": 200
      }
    }
  ],
  "missing_parameters": [],
  "notes": []
}
```

angle_deg=200 przekracza limit 160 stopni. Błąd zakresu, runnable=False.

## Before / after

| Metryka | Before | After |
|---|---|---|
| Action accuracy | 78.57% | 100.00% |
| Parameter accuracy | 78.57% | 92.86% |
| Full-plan success | 78.57% | 92.86% |
| Hallucination rate | 21.43% | 7.14% |
| Missing detection | 33.33% | 66.67% |
| JSON validity | 100.00% | 100.00% |
| Średni czas [s] | 23.01 | 25.23 |
| Średnia szybkość [tokens/s] | 5.35 | 5.26 |

14 prób ocenianych semantycznie; test 14 obserwacyjny. JSON i średnie: 15 prób; braki: 3 próby. Full-plan success obejmuje prawidłowe INCOMPLETE, nie oznacza runnable. Skoring akcji dostosowany do zmiany kontraktu (wcześniej pomijanie, teraz null); polecenia niezmienione. Requesty bez historii, wspólny prefiks promptu może korzystać z cache. Pojedyncze uruchomienie każdego przypadku, więc wyniki nie dowodzą stabilności między powtórzeniami.

## Trzy kluczowe przypadki

| Polecenie | Before | After |
|---|---|---|
| Ustaw piezo. | value_v=0, pytanie o napięcie | value_v=null; INCOMPLETE, pytanie walidatora |
| Ustaw drugą łopatkę. | angle_deg=90 | angle_deg=35; nadal halucynacja, formalnie COMPLETE |
| Ustaw temperaturę. | value_c=25 | value_c=null; INCOMPLETE, pytanie walidatora |

## Pozostałe problemy

- Test 4: model skopiował 35 z przykładu mimo zakazu. Strukturalny walidator przyjmuje tę liczbę, ponieważ nie jest parserem naturalnego języka. Null rozwiązuje reprezentację braków, ale nie dowodzi pochodzenia nie-nullowych wartości.
- Test 14: model nadal przyjmuje value_v=10 bez jawnej jednostki i bez pytania. Wynik wyłącznie obserwacyjny; nie dodano parsera ani automatycznego przeliczania jednostek.
- Średni czas wzrósł z 23.01 do 25.23 s; szybkość 5.35 -> 5.26 tokens/s. Zestaw pojedynczych prób, odmienne długości odpowiedzi i stan pamięci/cache ograniczają porównanie wydajności.
- Zachowane missing_parameters od modelu są konserwatywną dodatkową blokadą (np. operacje nieobsługiwane). Dla null pytania są deterministyczne i nie zależą od deklaracji kompletności modelu.
- Stabilizacja nadal nieobsługiwana i blokowana. Nie dodano nowej akcji ani clarification flow.
- Produkcyjnego modelu nie przełączono. Warto osobno zbadać odporność na kopiowanie przykładów, zanim model zostanie użyty do planów wykonywalnych.

## Walidacja

```sh
python3 -m unittest tests_x.test_measurement_assistant
python3 -m py_compile modules/measurement_assistant/actions.py modules/measurement_assistant/plan_schema.py modules/measurement_assistant/backend.py modules/measurement_assistant/context_builder.py tests_x/benchmark_measurement_assistant_models.py
python3 tests_x/benchmark_measurement_assistant_models.py
```

42 testy: OK. Benchmark 15/15 requestów zakończonych poprawnym JSON; zakresy i null ocenione niezależnie. Wyniki po naprawie punktacji przeliczono z zachowanych surowych odpowiedzi bez ponownego generowania i bez zmian CASES.

Pełne prompty, schema, payloady i odpowiedzi: qwen35_2b_results.json. Wymagana pełna tabela testów: qwen35_2b_report.md.