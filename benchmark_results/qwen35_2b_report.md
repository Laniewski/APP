# Benchmark Qwen3.5-2B Q4_K_M

15 pojedynczych prób; temperature=0, context=2048, threads=4, max_tokens=400.
Myślenie i projektor wyłączone. Brak wykonania sprzętowego. Surowe odpowiedzi bez napraw semantycznych.

## Ograniczenia i sposób oceny

Current contract preserves incomplete actions with nullable arguments. PlanValidator derives missing questions independently of model declarations. Null is INCOMPLETE, never runnable; structural/range/type failures remain INVALID.

Requesty zachowują domyślne cache promptu backendu. Każda rozmowa jest niezależna, ale wspólny prefiks może być ponownie używany. Pierwszy request miał zimny cache promptu; timings zapisują cache_n i prompt_n dla każdej próby.

Ocena akcji uwzględnia aktualny prompt: niekompletne akcje pozostają z null, a pytania wyznacza walidator. Oczekiwania użytkownika z null są zachowane w JSON jako expected_intent. validator_passed oznacza brak errors; runnable zapisane osobno i uwzględnia missing_parameters. Full-plan success wymaga poprawnych akcji, kolejności, parametrów, JSON, walidatora i wykrycia braków. Test 14 jest wyłącznie obserwacyjny i wyłączony z metryk semantycznych (14 prób; detekcja braków: 3 próby). JSON validity obejmuje 15 prób. Parameter accuracy jest odsetkiem prób z poprawnym całym zestawem parametrów. Detekcja pytań używa jawnych słów kluczowych; surowe pytania dostępne poniżej. Halucynacja obejmuje wymyślone lub błędne liczby oraz nieoczekiwane parametry. Tokens/s to szybkość dekodowania z timings, czas obejmuje pełny request HTTP. Wszystkie 15 prób bez historii rozmowy.

| test | correct_actions | correct_order | correct_parameters | missing_detected | hallucinated_parameter | valid_json | validator_passed | time_s | tokens_s |
|---|---|---|---|---|---|---|---|---|---|
| 1 | tak | tak | tak | — | nie | tak | tak | 44.50 | 5.85 |
| 2 | tak | tak | tak | tak | nie | tak | tak | 16.13 | 5.77 |
| 3 | tak | tak | tak | — | nie | tak | tak | 22.24 | 5.58 |
| 4 | tak | tak | nie | nie | tak | tak | tak | 19.73 | 5.78 |
| 5 | tak | tak | tak | — | nie | tak | tak | 26.29 | 5.57 |
| 6 | tak | tak | tak | — | nie | tak | tak | 25.13 | 5.45 |
| 7 | tak | tak | tak | — | nie | tak | tak | 34.81 | 5.24 |
| 8 | tak | tak | tak | tak | nie | tak | tak | 16.77 | 5.26 |
| 9 | tak | tak | tak | — | nie | tak | tak | 15.69 | 5.17 |
| 10 | tak | tak | tak | — | nie | tak | tak | 36.25 | 5.01 |
| 11 | tak | tak | tak | — | nie | tak | tak | 21.18 | 4.96 |
| 12 | tak | tak | tak | — | nie | tak | tak | 24.07 | 4.91 |
| 13 | tak | tak | tak | — | nie | tak | tak | 29.30 | 4.81 |
| 14 | — | — | — | — | — | tak | tak | 20.80 | 4.83 |
| 15 | tak | tak | tak | — | nie | tak | tak | 25.61 | 4.66 |

## Metryki

- action_accuracy: 100.00%
- parameter_accuracy: 92.86%
- missing_parameter_detection_accuracy: 66.67%
- hallucination_rate: 7.14%
- json_validity_rate: 100.00%
- full_plan_success_rate: 92.86%
- mean_time_s: 25.23
- mean_tokens_s: 5.26

## Before / after

| Metryka | Before | After |
|---|---|---|
| full_plan_success_rate | 78.57% | 92.86% |
| hallucination_rate | 21.43% | 7.14% |
| missing_parameter_detection_accuracy | 33.33% | 66.67% |
| json_validity_rate | 100.00% | 100.00% |
| mean_time_s | 23.01 | 25.23 |
| mean_tokens_s | 5.35 | 5.26 |

Polecenia testowe identyczne. Before oceniał pomijanie niekompletnych akcji zgodnie ze starym promptem; after wymaga zachowania akcji z null. Full-plan success obejmuje prawidłowy INCOMPLETE, który pozostaje niewykonywalny.


## Błędy zaobserwowane

- Test 4: hallucinated_parameter=True; missing_detected=False; validator_passed=True.

## Wykonanie i integralność

```sh
python3 -m py_compile tests_x/benchmark_measurement_assistant_models.py
python3 tests_x/benchmark_measurement_assistant_models.py
```

Komenda serwera:
```sh
/home/malina/.local/share/app-v2/llama.cpp/build/bin/llama-server -hf openresearchtools/Qwen3.5-2B-GGUF:Q4_K_M --host 127.0.0.1 --port 18766 -c 2048 -t 4 -b 256 -ub 128 --cache-ram 0 -ngl 0 --parallel 1 --no-mmproj --reasoning off
```

Ładowanie serwera: 11.71 s.
Istniejące źródła bez zmian: True.
Utworzone pliki: tests_x/benchmark_measurement_assistant_models.py, benchmark_results/qwen35_2b_results.json, benchmark_results/qwen35_2b_report.md, benchmark_results/qwen35_2b_server.log.

## Najczęstsze błędy i rekomendacje

- Rozdzielić kontrakt planu niekompletnego od planu gotowego: dopuścić steps [] albo reprezentację brakujących parametrów. Obecnie poprawne pytanie nie mieści się w schema.
- W definicjach i few-shot dodać polskie synonimy: płytka piezo, nastawnik polaryzacji; liczby słowne i numery łopatek.
- Dodać przykłady wieloetapowe z zachowaniem nietypowej kolejności oraz przypadek liczby bez jednostki z pytaniem o jednostkę.
- Każdą wymyśloną wartość oceniać niezależnie od walidatora; zgodność ze schema nie oznacza zgodności z poleceniem.
- Nie przełączać modelu APP na podstawie pojedynczego zestawu; powtórzyć ocenę po uzgodnieniu kontraktu. Ten benchmark niczego w aplikacji nie zmienia.

## Pełne odpowiedzi

### Test 1: Ustaw piezo na 12 V.

```text
{
  "title": "Ustaw piezo na 12 V.",
  "steps": [
    {
      "description": "Ustaw napięcie piezo MDT694B.",
      "action": "set_piezo_voltage",
      "args": {
        "value_v": 12
      }
    }
  ],
  "missing_parameters": [],
  "notes": []
}
```

Walidator: {"errors": [], "missing_parameters": [], "runnable": true, "status": "COMPLETE"}

### Test 2: Ustaw piezo.

```text
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

Walidator: {"errors": [], "missing_parameters": ["Krok 1: Podaj napięcie piezo."], "runnable": false, "status": "INCOMPLETE"}

### Test 3: Ustaw drugą łopatkę na 30 stopni.

```text
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

Walidator: {"errors": [], "missing_parameters": [], "runnable": true, "status": "COMPLETE"}

### Test 4: Ustaw drugą łopatkę.

```text
{
  "title": "Ustaw drugą łopatkę",
  "steps": [
    {
      "description": "Ustaw kąt łopatki MPC220 na 35 stopni.",
      "action": "set_polarization_angle",
      "args": {
        "paddle": 2,
        "angle_deg": 35
      }
    }
  ],
  "missing_parameters": [],
  "notes": []
}
```

Walidator: {"errors": [], "missing_parameters": [], "runnable": true, "status": "COMPLETE"}

### Test 5: Ustaw temperaturę na 37 stopni i rozpocznij pomiar.

```text
{
  "title": "Ustaw temperaturę na 37 stopni i rozpocznij pomiar",
  "steps": [
    {
      "description": "Ustaw temperaturę na 37 stopni i rozpocznij pomiar.",
      "action": "set_temperature",
      "args": {
        "value_c": 37
      }
    },
    {
      "description": "Rozpocznij pomiar.",
      "action": "start_measurement",
      "args": {}
    }
  ],
  "missing_parameters": [],
  "notes": []
}
```

Walidator: {"errors": [], "missing_parameters": [], "runnable": true, "status": "COMPLETE"}

### Test 6: Poczekaj 4 sekundy i zatrzymaj pomiar.

```text
{
  "title": "Poczekaj 4 sekundy i zatrzymaj pomiar.",
  "steps": [
    {
      "description": "Poczekaj podaną liczbę sekund.",
      "action": "wait",
      "args": {
        "seconds": 4
      }
    },
    {
      "description": "Zatrzymaj ADS1263.",
      "action": "stop_measurement",
      "args": {}
    }
  ],
  "missing_parameters": [],
  "notes": []
}
```

Walidator: {"errors": [], "missing_parameters": [], "runnable": true, "status": "COMPLETE"}

### Test 7: Ustaw piezo na 20 V i drugą łopatkę na 45 stopni.

```text
{
  "title": "Ustaw piezo na 20 V i drugą łopatkę na 45 stopni.",
  "steps": [
    {
      "description": "Ustaw napięcie piezo na 20 V.",
      "action": "set_piezo_voltage",
      "args": {
        "value_v": 20
      }
    },
    {
      "description": "Ustaw kąt drugiej łopatki na 45 stopni.",
      "action": "set_polarization_angle",
      "args": {
        "paddle": 2,
        "angle_deg": 45
      }
    }
  ],
  "missing_parameters": [],
  "notes": []
}
```

Walidator: {"errors": [], "missing_parameters": [], "runnable": true, "status": "COMPLETE"}

### Test 8: Ustaw temperaturę.

```text
{
  "title": "Ustaw temperaturę",
  "steps": [
    {
      "description": "Ustaw temperaturę zadaną przez użytkownika",
      "action": "set_temperature",
      "args": {
        "value_c": null
      }
    }
  ],
  "missing_parameters": [],
  "notes": []
}
```

Walidator: {"errors": [], "missing_parameters": ["Krok 1: Podaj temperaturę zadaną."], "runnable": false, "status": "INCOMPLETE"}

### Test 9: Rozpocznij pomiar.

```text
{
  "title": "Rozpocznij pomiar",
  "steps": [
    {
      "description": "Rozpocznij pomiar",
      "action": "start_measurement",
      "args": {}
    }
  ],
  "missing_parameters": [],
  "notes": []
}
```

Walidator: {"errors": [], "missing_parameters": [], "runnable": true, "status": "COMPLETE"}

### Test 10: Ustaw pierwszą łopatkę na 25 stopni, potem drugą na 50 stopni.

```text
{
  "title": "Ustawienie kąta polaryzacji",
  "steps": [
    {
      "description": "Ustaw pierwszą łopatkę na 25 stopni",
      "action": "set_polarization_angle",
      "args": {
        "paddle": 1,
        "angle_deg": 25
      }
    },
    {
      "description": "Ustaw drugą łopatkę na 50 stopni",
      "action": "set_polarization_angle",
      "args": {
        "paddle": 2,
        "angle_deg": 50
      }
    }
  ],
  "missing_parameters": [],
  "notes": []
}
```

Walidator: {"errors": [], "missing_parameters": [], "runnable": true, "status": "COMPLETE"}

### Test 11: Ustaw płytkę piezo na 15 V.

```text
{
  "title": "Ustaw płytkę piezo na 15 V.",
  "steps": [
    {
      "description": "Ustaw napięcie piezo MDT694B.",
      "action": "set_piezo_voltage",
      "args": {
        "value_v": 15
      }
    }
  ],
  "missing_parameters": [],
  "notes": []
}
```

Walidator: {"errors": [], "missing_parameters": [], "runnable": true, "status": "COMPLETE"}

### Test 12: Ustaw drugi nastawnik polaryzacji na 40 stopni.

```text
{
  "title": "Ustaw drugi nastawnik polaryzacji na 40 stopni.",
  "steps": [
    {
      "description": "Ustaw kąt łopatki MPC220.",
      "action": "set_polarization_angle",
      "args": {
        "paddle": 2,
        "angle_deg": 40
      }
    }
  ],
  "missing_parameters": [],
  "notes": []
}
```

Walidator: {"errors": [], "missing_parameters": [], "runnable": true, "status": "COMPLETE"}

### Test 13: Najpierw rozpocznij pomiar, potem ustaw piezo na 10 V.

```text
{
  "title": "Rozpocznij pomiar, ustaw piezo na 10 V",
  "steps": [
    {
      "description": "Rozpocznij pomiar",
      "action": "start_measurement",
      "args": {}
    },
    {
      "description": "Ustaw napięcie piezo",
      "action": "set_piezo_voltage",
      "args": {
        "value_v": 10
      }
    }
  ],
  "missing_parameters": [],
  "notes": []
}
```

Walidator: {"errors": [], "missing_parameters": [], "runnable": true, "status": "COMPLETE"}

### Test 14: Ustaw piezo na 10.

```text
{
  "title": "Ustaw piezo na 10.",
  "steps": [
    {
      "description": "Ustaw napięcie piezo MDT694B.",
      "action": "set_piezo_voltage",
      "args": {
        "value_v": 10
      }
    }
  ],
  "missing_parameters": [],
  "notes": []
}
```

Walidator: {"errors": [], "missing_parameters": [], "runnable": true, "status": "COMPLETE"}

### Test 15: Ustaw drugą łopatkę na dziewięćdziesiąt stopni.

```text
{
  "title": "Ustaw drugą łopatkę na dziewięćdziesiąt stopni.",
  "steps": [
    {
      "description": "Ustaw kąt łopatki MPC220.",
      "action": "set_polarization_angle",
      "args": {
        "paddle": 2,
        "angle_deg": 90
      }
    }
  ],
  "missing_parameters": [],
  "notes": []
}
```

Walidator: {"errors": [], "missing_parameters": [], "runnable": true, "status": "COMPLETE"}
