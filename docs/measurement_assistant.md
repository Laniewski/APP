# Lokalny asystent procedur

Wykonanie jest domyślnie wyłączone: `APP_AI_EXECUTION_ENABLED=0`.
Planowanie nie łączy urządzeń. Nieobsługiwane operacje oraz brakujące argumenty
blokują cały plan, także wtedy, gdy pozostałe kroki są poprawne.

## Przepływ

Polecenie → segmentacja z indeksami źródła → ekstrakcja Qwen w partiach po trzy
fragmenty → deterministyczna interpretacja ograniczonej gramatyki → niezależny
PlanValidator → podgląd i zapis → feature gate → ScriptBuilder → Runner →
MeasurementActions → istniejące kontrolery.

Model jest pomocniczym ekstraktorem. Jego wynik porównujemy z gramatyką i zapisujemy
osobno. Nie może dodawać dozwolonych operacji ani nadawać wartości argumentom
poza gramatyką. To konserwatywny kompromis: nowa parafraza może zostać zablokowana,
choć człowiek lub model rozumie ją poprawnie. `unsupported` oznacza również
„nie udało się bezpiecznie rozpoznać”, nie tylko brak funkcji urządzenia.

## Kontrakt

```json
{
  "title": "Plan procedury",
  "request": "Ustaw piezo.",
  "steps": [{"description": "Ustaw piezo", "action": "set_piezo_voltage",
             "args": {"value_v": null}, "source": [0, 11]}],
  "missing_parameters": [],
  "notes": []
}
```

`source` to półotwarty przedział indeksów znaków Pythona w oryginalnym `request`.
Interpunkcja dzieląca zdania może należeć do separatora, więc rzeczywiste indeksy
należy odczytać z wygenerowanego planu. Opis jest kopią fragmentu, a nie prozą LLM.
Walidator ponownie wyznacza akcje, argumenty, kolejność, opisy i indeksy z request.

- COMPLETE: wszystkie wymagane wartości jawne i prawidłowe; brak unsupported.
- INCOMPLETE: wymagany argument `null`. Pytania wyznacza rejestr, nie LLM.
- INVALID: unsupported/unknown, błędny typ/zakres, zmienione źródło lub plan.

Starsze plany bez request/source zachowano dla zgodności API; bez przekazanego
polecenia można sprawdzić tylko ich strukturę. Nowy backend zawsze dołącza źródło.
Nie należy przekazywać surowego wyniku modelu bezpośrednio do Runnera.

`unsupported` ma `args={}` i nie należy do rejestru wykonywalnych akcji.
„Włącz grzałkę”, „zapisz plik”, stabilizacja i mail pozostają w kolejności kroków.
Liczba mnoga „łopatki” oznacza obie dostępne łopatki, kolejno 1 i 2.
Brak numeru w liczbie pojedynczej daje `paddle=null`.
Jednostki bez dopisku: C, V, stopnie, sekundy. Inne jednostki nie są przeliczane.

## Model i zasoby

Domyślnie Qwen3.5-2B Q4_K_M: najpierw plik
`~/.local/share/app-v2/models/Qwen3.5-2B-Q4_K_M.gguf`, następnie już istniejący cache
repozytorium `openresearchtools/Qwen3.5-2B-GGUF`. Nie ma automatycznego pobierania.
`APP_AI_MODEL` nadpisuje wybór. Kontekst 2048, trzy wątki CPU, jeden slot,
`--no-mmproj --reasoning off`. Zmienne `APP_AI_BINARY`, `APP_AI_PORT`,
`APP_AI_THREADS`, `APP_AI_TIMEOUT`, `APP_AI_SCHEMA_FORMAT` pozostają dostępne.

Prompt nie zawiera few-shot ani antyprzykładów. Każda partia ma maksymalnie trzy
fragmenty, 400 tokenów wyjścia i jedną próbę naprawy struktury. Limit wejścia:
4000 znaków, 50 fragmentów; partia ponad 1000 znaków jest odrzucana. Bardzo długie
lub nietypowo tokenizowane polecenie nadal może przekroczyć kontekst serwera.
Anulowanie sprawdzamy również między partiami i po odebraniu odpowiedzi.

## Artefakty i testy

W `runs/` zapisywane są request, finalny plan, lista surowych odpowiedzi LLM,
metryki wszystkich prób i log. Kopiowanie JSON w GUI kopiuje finalny plan;
surowe odpowiedzi są dostępne w `llm_response.json`. Uszkodzone odpowiedzi także
są zachowane. ScriptBuilder ponownie waliduje przed zapisem i usuwa stary skrypt,
gdy zastępuje plan niewykonywalnym. Runner sprawdza zgodność bajtów skryptu
z deterministycznie wygenerowanym kodem.

```sh
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests_x
.venv/bin/python tests_x/benchmark_measurement_assistant_models.py --mode before
.venv/bin/python tests_x/benchmark_measurement_assistant_models.py --mode after
.venv/bin/python tests_x/benchmark_measurement_assistant_models.py --mode no_examples
```

Benchmark oczekuje już uruchomionego lokalnego serwera na porcie 18767. Nie
uruchamia sprzętu ani nie pobiera modeli. `--holdout` dodaje oddzielny pomiar
parafraz spoza gramatyki. Pełna metodologia i wyniki: `benchmark_results/redesign/`.
