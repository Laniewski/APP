# Benchmark Qwen3.5-2B Q4_K_M

15 pojedynczych prób; temperature=0, context=2048, threads=4, max_tokens=400.
Myślenie i projektor wyłączone. Brak wykonania sprzętowego. Surowe odpowiedzi bez napraw semantycznych.

## Ograniczenia i sposób oceny

Current prompt omits incomplete actions and asks questions, but schema and validator require steps >= 1 and all numeric arguments; null is forbidden. Missing-only requests therefore cannot satisfy both contracts.

Requesty zachowują domyślne cache promptu backendu. Każda rozmowa jest niezależna, ale wspólny prefiks może być ponownie używany. Pierwszy request miał zimny cache promptu; timings zapisują cache_n i prompt_n dla każdej próby.

Ocena akcji uwzględnia aktualny prompt: niekompletne akcje mają być pominięte, a brak opisany pytaniem. Oczekiwania użytkownika z null są zachowane w JSON jako expected_intent. validator_passed oznacza brak errors; runnable zapisane osobno i uwzględnia missing_parameters. Full-plan success wymaga poprawnych akcji, kolejności, parametrów, JSON, walidatora i wykrycia braków. Test 14 jest wyłącznie obserwacyjny i wyłączony z metryk semantycznych (14 prób; detekcja braków: 3 próby). JSON validity obejmuje 15 prób. Parameter accuracy jest odsetkiem prób z poprawnym całym zestawem parametrów. Detekcja pytań używa jawnych słów kluczowych; surowe pytania dostępne poniżej. Halucynacja obejmuje wymyślone lub błędne liczby oraz nieoczekiwane parametry. Tokens/s to szybkość dekodowania z timings, czas obejmuje pełny request HTTP. Wszystkie 15 prób bez historii rozmowy.

| test | correct_actions | correct_order | correct_parameters | missing_detected | hallucinated_parameter | valid_json | validator_passed | time_s | tokens_s |
|---|---|---|---|---|---|---|---|---|---|
| 1 | tak | tak | tak | — | nie | tak | tak | 43.94 | 5.83 |
| 2 | nie | nie | nie | tak | tak | tak | tak | 18.84 | 5.52 |
| 3 | tak | tak | tak | — | nie | tak | tak | 19.31 | 5.62 |
| 4 | nie | nie | nie | nie | tak | tak | tak | 20.30 | 5.46 |
| 5 | tak | tak | tak | — | nie | tak | tak | 23.14 | 5.39 |
| 6 | tak | tak | tak | — | nie | tak | tak | 22.45 | 5.54 |
| 7 | tak | tak | tak | — | nie | tak | tak | 28.93 | 5.34 |
| 8 | nie | nie | nie | nie | tak | tak | tak | 15.95 | 5.53 |
| 9 | tak | tak | tak | — | nie | tak | tak | 14.23 | 5.55 |
| 10 | tak | tak | tak | — | nie | tak | tak | 31.19 | 5.32 |
| 11 | tak | tak | tak | — | nie | tak | tak | 17.69 | 5.27 |
| 12 | tak | tak | tak | — | nie | tak | tak | 20.28 | 5.17 |
| 13 | tak | tak | tak | — | nie | tak | tak | 26.68 | 4.95 |
| 14 | — | — | — | — | — | tak | tak | 18.57 | 4.96 |
| 15 | tak | tak | tak | — | nie | tak | tak | 23.60 | 4.84 |

## Metryki

- action_accuracy: 78.57%
- parameter_accuracy: 78.57%
- missing_parameter_detection_accuracy: 33.33%
- hallucination_rate: 21.43%
- json_validity_rate: 100.00%
- full_plan_success_rate: 78.57%
- mean_time_s: 23.01
- mean_tokens_s: 5.35

## Błędy zaobserwowane

- Test 2: hallucinated_parameter=True; missing_detected=True; validator_passed=True.
- Test 4: hallucinated_parameter=True; missing_detected=False; validator_passed=True.
- Test 8: hallucinated_parameter=True; missing_detected=False; validator_passed=True.

## Wykonanie i integralność

```sh
python3 -m py_compile tests_x/benchmark_measurement_assistant_models.py
python3 tests_x/benchmark_measurement_assistant_models.py
```

Komenda serwera:
```sh
/home/malina/.local/share/app-v2/llama.cpp/build/bin/llama-server -hf openresearchtools/Qwen3.5-2B-GGUF:Q4_K_M --host 127.0.0.1 --port 18766 -c 2048 -t 4 -b 256 -ub 128 --cache-ram 0 -ngl 0 --parallel 1 --no-mmproj --reasoning off
```

Ładowanie serwera: 23.15 s.
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
  "title": "Procedura pomiarowa",
  "steps": [
    {
      "description": "Ustaw napięcie piezo",
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

Walidator: {"errors": [], "missing_parameters": [], "runnable": true}

### Test 2: Ustaw piezo.

```text
{
  "title": "Procedura pomiarowa",
  "steps": [
    {
      "description": "Ustaw napięcie piezo",
      "action": "set_piezo_voltage",
      "args": {
        "value_v": 0
      }
    }
  ],
  "missing_parameters": [
    "Podaj wartość napięcia piezo."
  ],
  "notes": []
}
```

Walidator: {"errors": [], "missing_parameters": ["Podaj wartość napięcia piezo."], "runnable": false}

### Test 3: Ustaw drugą łopatkę na 30 stopni.

```text
{
  "title": "Procedura pomiarowa",
  "steps": [
    {
      "description": "Ustaw kąt jednej łopatki MPC220",
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

Walidator: {"errors": [], "missing_parameters": [], "runnable": true}

### Test 4: Ustaw drugą łopatkę.

```text
{
  "title": "Procedura pomiarowa",
  "steps": [
    {
      "description": "Ustaw kąt polaryzacji dla drugiej łopatki",
      "action": "set_polarization_angle",
      "args": {
        "paddle": 2,
        "angle_deg": 90.0
      }
    }
  ],
  "missing_parameters": [],
  "notes": []
}
```

Walidator: {"errors": [], "missing_parameters": [], "runnable": true}

### Test 5: Ustaw temperaturę na 37 stopni i rozpocznij pomiar.

```text
{
  "title": "Procedura pomiarowa",
  "steps": [
    {
      "description": "Ustaw temperaturę",
      "action": "set_temperature",
      "args": {
        "value_c": 37
      }
    },
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

Walidator: {"errors": [], "missing_parameters": [], "runnable": true}

### Test 6: Poczekaj 4 sekundy i zatrzymaj pomiar.

```text
{
  "title": "Procedura pomiarowa",
  "steps": [
    {
      "description": "Poczekaj na 4 sekundy",
      "action": "wait",
      "args": {
        "seconds": 4
      }
    },
    {
      "description": "Zatrzymaj pomiar",
      "action": "stop_measurement",
      "args": {}
    }
  ],
  "missing_parameters": [],
  "notes": []
}
```

Walidator: {"errors": [], "missing_parameters": [], "runnable": true}

### Test 7: Ustaw piezo na 20 V i drugą łopatkę na 45 stopni.

```text
{
  "title": "Procedura pomiarowa",
  "steps": [
    {
      "description": "Ustaw napięcie piezo",
      "action": "set_piezo_voltage",
      "args": {
        "value_v": 20
      }
    },
    {
      "description": "Ustaw kąt drugiej łopatki",
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

Walidator: {"errors": [], "missing_parameters": [], "runnable": true}

### Test 8: Ustaw temperaturę.

```text
{
  "title": "Procedura pomiarowa",
  "steps": [
    {
      "description": "Ustaw temperaturę",
      "action": "set_temperature",
      "args": {
        "value_c": 25.0
      }
    }
  ],
  "missing_parameters": [],
  "notes": []
}
```

Walidator: {"errors": [], "missing_parameters": [], "runnable": true}

### Test 9: Rozpocznij pomiar.

```text
{
  "title": "Procedura pomiarowa",
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

Walidator: {"errors": [], "missing_parameters": [], "runnable": true}

### Test 10: Ustaw pierwszą łopatkę na 25 stopni, potem drugą na 50 stopni.

```text
{
  "title": "Procedura pomiarowa",
  "steps": [
    {
      "description": "Ustaw kąt pierwszej łopatki",
      "action": "set_polarization_angle",
      "args": {
        "paddle": 1,
        "angle_deg": 25
      }
    },
    {
      "description": "Ustaw kąt drugiej łopatki",
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

Walidator: {"errors": [], "missing_parameters": [], "runnable": true}

### Test 11: Ustaw płytkę piezo na 15 V.

```text
{
  "title": "Procedura pomiarowa",
  "steps": [
    {
      "description": "Ustaw napięcie piezo",
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

Walidator: {"errors": [], "missing_parameters": [], "runnable": true}

### Test 12: Ustaw drugi nastawnik polaryzacji na 40 stopni.

```text
{
  "title": "Procedura pomiarowa",
  "steps": [
    {
      "description": "Ustaw kąt polaryzacji",
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

Walidator: {"errors": [], "missing_parameters": [], "runnable": true}

### Test 13: Najpierw rozpocznij pomiar, potem ustaw piezo na 10 V.

```text
{
  "title": "Procedura pomiarowa",
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

Walidator: {"errors": [], "missing_parameters": [], "runnable": true}

### Test 14: Ustaw piezo na 10.

```text
{
  "title": "Procedura pomiarowa",
  "steps": [
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

Walidator: {"errors": [], "missing_parameters": [], "runnable": true}

### Test 15: Ustaw drugą łopatkę na dziewięćdziesiąt stopni.

```text
{
  "title": "Procedura pomiarowa",
  "steps": [
    {
      "description": "Ustaw kąt polaryzacji dla drugiej łopatki MPC220",
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

Walidator: {"errors": [], "missing_parameters": [], "runnable": true}
