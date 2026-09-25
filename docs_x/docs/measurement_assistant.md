# Lokalny asystent pomiarów APP v2

Panel po prawej otwiera przycisk `AI ›`. Domyślnie jest ukryty.
Model ładuje się dopiero po „Utwórz plan”. Generowanie nie wykonuje pomiaru.
Domyślnie wykonanie AI jest wyłączone i Start jest nieaktywny. Dopiero po
jawnym włączeniu wykonania użytkownik sprawdza plan, ręcznie łączy potrzebne
urządzenia i naciska Start.

## Przepływ

```text
Użytkownik → GUI → MeasurementAssistantController → LLMBackend
→ lokalny llama-server → JSON → PlanValidator → ScriptBuilder
→ runs/<czas>/ (JSON, metryki, log)
→ tylko przy execution enabled: script.py → Runner (QThread) → MeasurementActions
→ queued signals → istniejące controllery APP v2 → ich workery → sprzęt
```

Runner nie wywołuje widgetów z obcego wątku. Most wykonuje publiczne metody
kontrolerów w wątku GUI i czeka na sygnały zakończenia z istniejących workerów.
Ręczne sterowanie jest zablokowane podczas procedury, Stop pozostaje dostępny.
Nie powstała druga implementacja sterowników.

## Dostępne akcje i publiczne API

| Akcja | Publiczna metoda |
| --- | --- |
| `set_temperature(value_c)` | `TC200Controller.set_temperature(value_c)` |
| `set_piezo_voltage(value_v)` | `MDT694BController.set_voltage(value_v)` |
| `set_polarization_angle(paddle, angle_deg)` | `MPC220Controller.set_angle(paddle, angle_deg)` |
| `start_measurement()` | `MeasurementController.start_measurement()` |
| `stop_measurement()` | `MeasurementController.stop_measurement()` |
| `wait(seconds)` | przerywalne oczekiwanie w workerze asystenta |

Nowe minimalne API to `TC200Controller.is_connected()`,
`MPC220Controller.is_connected()/is_optimizing()/set_angle()`.
Dodane sygnały `voltage_set` i `angle_set` potwierdzają zakończenie operacji,
a nie tylko wysłanie żądania. Zakres temperatury i kąta pochodzi z istniejących
stałych; zakres napięcia nadal sprawdza sterownik MDT694B.

Ustawienie temperatury to **nastawa**, nie włączenie grzałki ani stabilizacja.
Nie ma jeszcze akcji wykrywania stabilizacji. Prośba „poczekaj aż się
ustabilizuje” powinna zwrócić brakujące kryteria i informację o niedostępnej akcji;
nie wolno zastępować tego arbitralnym czasem. Braki blokują Start.
Pomiary używają kanałów już wybranych w GUI.

## Instalacja i uruchamianie

Model: [Qwen/Qwen2.5-1.5B-Instruct-GGUF](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF),
plik `qwen2.5-1.5b-instruct-q4_k_m.gguf` (Q4_K_M, 1117320736 bajtów,
1065,6 MiB). Zweryfikowany SHA256:
`6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e`.
Porównawczo pobrano też 0.5B Q4_K_M (491400032 bajty); jest poza repozytorium,
ale nie jest domyślny: zbyt często mylił brakujące parametry.
Silnik: oficjalny [ggml-org/llama.cpp](https://github.com/ggml-org/llama.cpp).
Oba są poza repozytorium:

```text
~/.local/share/app-v2/llama.cpp/
~/.local/share/app-v2/llama.cpp/build/bin/llama-server
~/.local/share/app-v2/models/qwen2.5-1.5b-instruct-q4_k_m.gguf
~/.local/share/app-v2/models/llama-server.log
```

CMake zainstalowano w istniejącym `.venv`, nie globalnie. Kompilacja ARM64 Release:

```bash
.venv/bin/python -m pip install cmake
mkdir -p ~/.local/share/app-v2/models
git clone --depth 1 https://github.com/ggml-org/llama.cpp ~/.local/share/app-v2/llama.cpp
.venv/bin/cmake -S ~/.local/share/app-v2/llama.cpp -B ~/.local/share/app-v2/llama.cpp/build -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=OFF -DGGML_NATIVE=ON -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_CURL=OFF
.venv/bin/cmake --build ~/.local/share/app-v2/llama.cpp/build --target llama-server -j3
curl -fL --retry 2 -o ~/.local/share/app-v2/models/qwen2.5-1.5b-instruct-q4_k_m.gguf https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf
```

Aplikacja z terminala z dostępem do graficznej sesji Raspberry Pi:

```bash
cd /home/malina/APPv2
APP_AI_EXECUTION_ENABLED=0 .venv/bin/python main.py
```

Ręczny serwer (opcjonalny; asystent uruchamia go automatycznie):

```bash
~/.local/share/app-v2/llama.cpp/build/bin/llama-server -m ~/.local/share/app-v2/models/qwen2.5-1.5b-instruct-q4_k_m.gguf --host 127.0.0.1 --port 8080 -c 2048 -t 3 -b 256 -ub 128 --cache-ram 0 -ngl 0 --parallel 1
```

Backend łączy się wyłącznie z `127.0.0.1`, bez usług chmurowych i proxy.
Nie zmieniaj hosta ręcznego serwera na `0.0.0.0`.
Zmienne: `APP_AI_BINARY`, `APP_AI_MODEL`, `APP_AI_PORT`, `APP_AI_CONTEXT`,
`APP_AI_THREADS`, `APP_AI_TIMEOUT`, `APP_AI_EXECUTION_ENABLED`, `APP_AI_SCHEMA_FORMAT`. Domyślnie: port 8080, kontekst 2048,
3 wątki, timeout 120 s; batch 256, microbatch 128 ograniczają szczyt pamięci.
Cache RAM promptów jest wyłączony (`--cache-ram 0`), zamiast domyślnego limitu
8192 MiB tej wersji llama.cpp. Host nie jest konfigurowalny.
Shutdown zatrzymuje tylko serwer uruchomiony przez ten backend, nie ręczny serwer.

## Historia, bezpieczeństwo i Stop

`runs/YYYY-MM-DD_HH-MM-SS/` zawiera `request.txt`, `plan.json`,
`llm_response.json`, `metrics.json` i `run.log`. `script.py` powstaje tylko
przy włączonym execution i poprawnym, kompletnym planie. Przy kolizji czasu powstaje sufiks. Plan z brakami ma zapisany JSON,
ale nie skrypt. Dodatkowy `llm_response.json` zachowuje oryginalną odpowiedź
przed normalizacją (nigdy nie jest źródłem kodu Runnera). `runs/` jest ignorowane
przez Git. Późniejszy eksport z GUI można
zapisać jako `data.csv` w tym samym katalogu — nie ma dodatkowego bufora danych
ani automatycznego eksportu w asystencie.

LLM zwraca tylko JSON: ścisły parser odrzuca markdown, powtórzone klucze i NaN.
Schemat i walidator korzystają z tego samego `ACTION_REGISTRY` co prompt.
Nieznane akcje, nadmiarowe argumenty, błędne typy i niepełne plany blokują Start.
Dodatkowy, niezależny od LLM bezpiecznik rozpoznaje wzmianki o stabilizacji
(`stabil`, `stable`, `steady state`) i dodaje brakujące kryteria do planu.
Taki plan nie otrzyma skryptu nawet wtedy, gdy model zadeklaruje kompletność
albo wymyśli `wait`. To konserwatywna blokada, nie ogólny parser języka.
Jeśli model opisze krok `wait` jako stabilizację, krok zostaje odrzucony
z wykonawczego planu (nie poprawiamy jego liczby sekund); surowa odpowiedź
pozostaje w `llm_response.json`. Cały plan nadal jest zablokowany.
Bezpiecznik może zablokować również zdanie negujące stabilizację,
wymagając przeformułowania.
Opisy i notatki nigdy nie stają się kodem. Python tworzy wyłącznie ScriptBuilder;
Runner porównuje skrypt z ponownie wygenerowanym kodem i importuje sprawdzony
snapshot. Nie wykonuje kodu LLM, importów LLM, shell ani dowolnych ścieżek LLM.
To ograniczenie techniczne, nie gwarancja poprawności fizycznej planu: użytkownik
nadal musi sprawdzić kolejność i wartości przed Start.

Stop ustawia `stop_event`, przerywa wait i dalsze kroki, a bezpiecznie zatrzymuje
pomiar ADS rozpoczęty przez asystenta. Nie zatrzymuje cudzej ręcznej sesji przy
błędzie Start. Nie zabija workerów urządzeń. Rozpoczęta komenda temperatury,
napięcia lub ruch łopatki może dokończyć się; Stop nie cofa nastaw i nie wyłącza
grzałki. Potwierdzenie kroku ma timeout 30 s. Nie używaj równoległego sterowania
spoza aplikacji.

## Rozszerzanie i testy

Nową akcję dodaj do `ACTION_REGISTRY` w `actions.py`, z opisem, argumentami
i ograniczeniami zaczerpniętymi z istniejących modułów. Dodaj jawną metodę mostu,
dispatch do publicznego API i potwierdzenie zakończenia. Prompt, JSON schema
i walidator odczytają rejestr automatycznie. Dołóż test fake i test złych argumentów.
Nie dodawaj akcji shell, dowolny Python ani bezpośredniego serial.

```bash
.venv/bin/python -m unittest discover -s tests_x -q
```

`tests_x` to zastany aktualny katalog po przeniesieniach użytkownika; nie odtworzono
ani nie usunięto wcześniejszych `tests`, `dane`, `testy`, `docs`.
Testy asystenta nie łączą urządzeń. Test GUI używa pustej listy portów.
Do dalszego rozwoju: jawna akcja stabilizacji z kryteriami, szersze próby jakości
planów, test ręczny urządzeń dopiero po osobnym zatwierdzeniu przez operatora.

## Próby na Raspberry Pi 5

Zbudowano llama.cpp Release ARM64 z commitu
`b04d4e567cd2fb8d2ded6e17d38dbbcfafe29063`, bez CUDA, 3 wątki.
Testy LLM tylko generowały plany na fake controllerach — żadnej temperatury,
napięcia ani pozycji nie ustawiono. Test głównego GUI przeszedł z pustą listą portów;
model pozostaje niezaładowany przy starcie. W całej istniejącej suite występują
zastane ostrzeżenia headless PyQtGraph `LabelItem.sizeHint`, mimo wyniku OK.

0.5B: około 714 MiB RSS, VmSwap 0, około 16–17 tokenów/s samej generacji,
ale błędne pytania o parametry. 1.5B poprawnie odtworzył pełną sekwencję piezo,
lecz sam prompt nie zapobiegł zgadywaniu czasu stabilizacji — dlatego dodano
niezależną blokadę. Stary artefakt tego benchmarku zachowano jako
`script.rejected.py`, a plan oznaczono jako niekompletny. Nie był wykonany.
Wyniki benchmarków w `runs/` są historią generowania, nie danymi z fizycznych pomiarów.

Końcowa konfiguracja 1.5B: kontekst 2048, 3 wątki, batch 256, microbatch 128,
cache RAM 0. Zwykły plan: 169 tokenów, 51,25 s razem z przetworzeniem promptu,
7,77 tokena/s samej generacji (3,30 tokena/s z narzutem promptu).
Szczyt serwera w tej próbie: RSS 2070864 KiB (około 2022 MiB), VmSwap 0.
System miał już zajęty swap po kompilacji i wcześniejszych próbach;
próbki `vmstat` podczas końcowej generacji wykazały `si=0, so=0`.
To pomiar w obecnym środowisku Remote SSH/VS Code, nie gwarancja pracy bez
swapu przy dowolnym obciążeniu innych programów. Testy: 105/105 (84 istniejące,
21 nowe). Nie przeprowadzono fizycznego pomiaru ani testu sterowania urządzeniami.
Końcowa prośba o stabilizację: 197 tokenów, 28,77 s, 8,08 tokena/s samej
generacji. Plan po normalizacji zawiera tylko nastawę temperatury, nastawę piezo
i start ADS; zawiera brakujące kryteria, Start jest zablokowany i brak `script.py`.
Oryginalny błędny `wait` jest zachowany wyłącznie w odpowiedzi diagnostycznej.
Serwer po benchmarku został zamknięty; start aplikacji nadal nie ładuje modelu.


## Tryb testowania planowania (domyślny)

`APP_AI_EXECUTION_ENABLED` domyślnie wynosi `0` (false). Wartości `1` i `true`
włączają wykonanie; `0` i `false` je wyłączają. Inne wartości powodują błąd
konfiguracji. Opcja jest odczytywana przy tworzeniu kontrolera, a zmiana wymaga
ponownego uruchomienia aplikacji. Blokady znajdują się w panelu, kontrolerze,
workerze wykonania, Runnerze oraz MeasurementActions (przed emisją komendy
oraz przed dispatch do urządzeń). Anulowanie w tym trybie nie steruje sprzętem.

```bash
APP_AI_EXECUTION_ENABLED=0 .venv/bin/python main.py
```

Rozwiń panel AI, wpisz polecenie lub wybierz przykład i kliknij „Utwórz plan”.
Przykłady tylko wstawiają tekst. Model ładuje się dopiero po żądaniu planu.
Panel pokazuje kroki, missing_parameters, konkretne błędy walidacji, status planu
oraz czas generowania, completion tokens i tokens/s. „Kopiuj JSON” kopiuje
oryginalną odpowiedź modelu (także niepoprawny JSON), a przy jej braku plan.json.
Przycisk „Rozpocznij” pozostaje wyłączony nawet dla kompletnego planu.

Późniejsze świadome włączenie wykonania:

```bash
APP_AI_EXECUTION_ENABLED=1 .venv/bin/python main.py
```

Wtedy dopiero kompletny, poprawny plan otrzymuje skrypt i umożliwia ręczny Start.
Zachowano ACTION_REGISTRY, PlanValidator, deterministyczny ScriptBuilder,
weryfikację skryptu Runnera i istniejące API kontrolerów.

Generowanie używa `temperature=0.0`, `max_tokens=400`, kontekstu 2048 (konfiguracja
nie dopuszcza większego), 3 wątków domyślnie i `--parallel 1`. Lokalny kod
llama.cpp b04d4e5 w `tools/server/server-common.cpp` obsługuje
`response_format: {type: json_object, schema: ...}`, więc to format domyślny.
Dla starszego binarnego serwera można ustawić `APP_AI_SCHEMA_FORMAT=legacy`,
co zachowuje wcześniejsze `response_format: {type: json_object}` i osobne
`json_schema`. Obie drogi kończą się ścisłym parse_response i niezależną walidacją.

Wyniki są w katalogu `runs/` w głównym katalogu repozytorium (domyślnie
`/home/malina/APPv2/runs/`), ignorowanym przez Git. Błędna odpowiedź JSON ma
`plan.json` z wartością null oraz oryginalny tekst w `llm_response.json`.
Metryki obejmują elapsed_s (generowanie z ewentualną pojedynczą próbą naprawy,
bez ładowania modelu), completion_tokens, tokens_per_s, valid, runnable,
missing_parameters_count i validation_errors. `runnable` opisuje kompletność
planu, niezależnie od uprawnienia execution. Nieznane metryki mają wartość null. Katalog żądania powstaje przed
generowaniem; przerwanie aplikacji pozostawia ślad z planem null i informacją
„Generowanie nieukończone lub przerwane”, zamiast tracić request.txt.
Prędkość pochodzi z timings serwera, a przy ich braku z tokenów/czasu żądania.

Log procesu uruchomionego przez APP:

```bash
tail -n 100 ~/.local/share/app-v2/models/llama-server.log
```

Przy `APP_AI_MODEL` log znajduje się w katalogu wskazanego modelu. Zewnętrzny
serwer prowadzi własny log; aplikacja nie zarządza jego procesem.

Weryfikacja bez sprzętu i bez uruchamiania modelu:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest tests_x.test_measurement_assistant tests_x.test_imports_and_gui -q
```
