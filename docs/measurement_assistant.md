# Asystent laboratoryjny — model rozumie język

`APP_AI_EXECUTION_ENABLED=0` pozostaje domyślne. Generowanie odpowiedzi nigdy
nie uruchamia procedury. Model pozostaje Qwen3.5-2B Q4_K_M przez llama-server.

## Dane i przepływ

GUI → controller/worker → `prompt_loader.load_messages` → backend → Qwen →
JSON → parser → techniczny PlanValidator → GUI.

- `answer`: odpowiedź na pytanie, puste steps, brak skryptu.
- `error`: komunikat modelu o niekompletnym/niedostępnym poleceniu, puste steps.
- `procedure`: niepuste kroki action/args, podgląd i walidacja.

Dopiero osobne kliknięcie Rozpocznij przy włączonym wykonaniu pozwala przejść:
PlanValidator → deterministyczny ScriptBuilder → Runner (sprawdza zgodność pliku
z generatorem) → MeasurementActions → istniejące kontrolery.
Runner ponownie waliduje plan przez ScriptBuilder. LLM nie generuje kodu.

Dane wejściowe modelu są w katalogu głównym `ai_context/`:

- `assistant_prompt.txt`: wyłącznie instrukcja dla modelu;
- `station_and_actions.json`: opisy urządzeń, argumenty, zakresy, przykłady,
  niekompletne polecenia i dostępność adapterów;
- `output_schema.json`: trzy rozłączne typy odpowiedzi;
- `data/`: własne małe materiały UTF-8 `.txt` i `.md`, także w podkatalogach.
  Loader sortuje ścieżki, oznacza źródła, pomija README i inne rozszerzenia.
  Nie ma RAG ani bazy wektorowej. Nie umieszczaj tu sekretów.

W Pythonie nie ma aktywnego parsera języka użytkownika. `grounding.py`,
`context_builder.py` i stare benchmarki zachowano jako historyczne eksperymenty,
ale nie uczestniczą w generowaniu ani walidacji. Historyczne plany są odrzucane.
Stary benchmark kończy się wskazaniem nowego narzędzia.

## Kontrakt wykonawczy

| Akcja | Argumenty | Adapter AI |
|---|---|---|
| set_temperature | value_c: 20–200 °C | tak |
| heater_on | brak | tak |
| heater_off | brak | tak |
| set_piezo_voltage | value_v: V | tak, efektywny zakres sprawdza sterownik |
| set_ramp_speed | ramp_rate_v_per_s: 0,01–1000 V/s | nie |
| start_ramp | target_voltage: V, ramp_rate_v_per_s: 0,01–1000 V/s | nie |
| stop_ramp | brak | nie |
| set_polarization_angle | paddle: 1, 2, "both"; angle_deg: 1–160° | tak |
| move_polarization | paddle: 1, 2, "both"; delta_deg: stopnie | tak |
| auto_polarization | brak | nie |
| start_measurement | brak | tak |
| stop_measurement | brak | tak |
| wait | seconds: 0–3600 s | tak |

`both` wykonuje kolejno ruch 1 i 2, z potwierdzeniem każdego ruchu. Ruch względny
korzysta z odczytu pozycji i istniejącego ograniczania wyniku do 1–160° w MPC220.
Grzałka czeka na istniejący sygnał zakończenia zmiany stanu.

Rampa GUI jest jednorazowym przebiegiem od aktualnego do docelowego napięcia.
Zakres napięcia odczytuje MDT694B (ograniczenia osi, systemu i przełącznika).
Pole prędkości GUI nie ma osobnego API kontrolera. Start/stop rampy nie mają
kompletnego kontraktu potwierdzeń dla runnera (np. start przy już osiągniętym
celu i stop nieaktywnej rampy). Dlatego te trzy akcje mają executable=false.

Automatyczna polaryzacja nie przyjmuje parametrów użytkownika. Wymaga MPC220,
MDT694B, aktywnego ADS1263 oraz grzałki potwierdzonej jako wyłączona lub odłączonego
TC200. Używa własnych stałych algorytmu (piezo 80–150 V, 20 V/s). Integracja AI
wymaga osobnej obsługi długiego wykonania, odrzucenia startu i anulowania zasobów;
obecnie executable=false. Nie zastępuj jej domyślnymi ruchami łopatek.

Walidator sprawdza zarówno schema, jak i aktualny katalog akcji. Kodowa allowlista
adapterów nie pozwala samą edycją JSON nadać uprawnień nowej akcji. Wszystkie
wymagane wartości muszą istnieć, null i bool jako liczba są niedozwolone.
Nieznane pola/akcje, złe typy i zakresy oraz niedostępny adapter blokują wykonanie.

Walidacja techniczna nie dowodzi, że model nie wymyślił poprawnej liczby.
Zakaz zgadywania egzekwujemy instrukcją modelu i mierzymy testami semantycznymi;
nie wprowadzamy drugiego parsera języka. Użytkownik sprawdza procedurę.

## Runtime i diagnostyka

Zachowano domyślne ścieżki Raspberry Pi i Windows oraz zmienne APP_AI_BINARY,
APP_AI_MODEL, APP_AI_PORT, APP_AI_THREADS, APP_AI_TIMEOUT, APP_AI_SCHEMA_FORMAT.
Nie ma automatycznego pobierania modelu. Pełny katalog i schema wymagają większego
kontekstu: domyślnie APP_AI_CONTEXT=16384 (do 32768), trzy wątki CPU, jeden slot.
Maksymalna odpowiedź to 2048 tokenów, temperatura 0, reasoning off.
Domyślny timeout HTTP wynosi 300 s ze względu na pierwszy prefill na Pi.
Dodatkowe materiały muszą mieścić się w kontekście; duży kontekst zwiększa RAM
oraz czas przetwarzania na Pi. Loader nie obcina po cichu materiałów.

Backend obsługuje nested schema w response_format oraz legacy json_schema.
Obcięta lub niepoprawna odpowiedź jest błędem, nigdy planem zastępczym.

`APP_AI_DEBUG_IO=1` zapisuje dokładne messages do `runs/last_model_input.txt`
i surową treść odpowiedzi do `runs/last_model_response.json` (przy błędzie modelu
plik może nie być poprawnym JSON). Flaga jest domyślnie wyłączona. Nie zapisuje
zmiennych środowiska ani konfiguracji systemowej. Materiały i tekst użytkownika
są częścią wejścia i pojawią się w diagnostyce. GUI nadal zapisuje historię
request/plan/llm_response/metrics/run.log w osobnych katalogach runs.

## Testy bez fizycznego sprzętu

```sh
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests_x -p 'test_*.py'
.venv/bin/python -m unittest tests_x.test_ai_pc_only tests_x.test_assistant_grounding
APP_AI_EXECUTION_ENABLED=0 .venv/bin/python tools/ai_plan_tester.py 'odpal grzanie'
APP_AI_EXECUTION_ENABLED=0 .venv/bin/python tools/test_assistant_model.py
```

Testy jednostkowe z atrapą odpowiedzi modelu sprawdzają transport i kontrakt,
nie potwierdzają rozumienia polskiego. Osobny tester rzeczywistego modelu mierzy
11 wymaganych przypadków i 5 parafraz nieobecnych w examples. Zapisuje wyniki
w `runs/model_acceptance.json`; nie importuje Qt, sterowników ani runnera.

## Wynik weryfikacji 2026-11-24

- Pełny zestaw aplikacji: **124 testy OK**, wyłącznie atrapy urządzeń i GUI offscreen.
- PC-only, standardowa biblioteka Pythona: **11 testów OK**.
- Rzeczywisty Qwen3.5-2B Q4_K_M na Raspberry Pi: **12/16**, tester zakończony kodem 1.
  Pełna akceptacja semantyczna **nie została osiągnięta**.
- Nie uruchamiano fizycznego sprzętu. Nie testowano uruchomienia na Windows;
  zachowano przenośną ścieżkę PC-only i zaktualizowano skrypt środowiska.

Wyniki wraz z sumami kontrolnymi kontekstu:
[`benchmark_results/model_driven_acceptance.json`](../benchmark_results/model_driven_acceptance.json).

Błędy rzeczywistego modelu:

| Polecenie | Oczekiwano | Zwrócono |
|---|---|---|
| ustaw łopatkę na 40 stopni | error: brak paddle | paddle="both" |
| daj pierwszą na 35 stopni | paddle=1 | paddle="both" |
| drugą przestaw o trzy stopnie | paddle=2 | paddle="both" |
| puść grzanie | heater_on | heater_off |

Odpowiedź na pytanie o cel zmiany polaryzacji ma poprawny typ `answer`, ale jest
błędna rzeczowo (model wymyślił zależność polaryzacji od napięcia piezo i grzałki).
Ten test, zgodnie z założeniami przy pustym data/, sprawdza wyłącznie typ.

Wcześniejsze próby promptu oraz trybu reasoning nie dały niezawodnego rozpoznania
braków. Końcowy kontekst ogranicza część błędów, ale model nadal nie spełnia całej
akceptacji. Nie dodano semantycznego parsera zastępczego. Wykonanie AI pozostaje
domyślnie wyłączone; poprawność struktury nie jest potwierdzeniem intencji.

Pierwsza odpowiedź w końcowym przebiegu zajęła około 194 s (z przetwarzaniem
kontekstu), kolejne około 7–37 s. Backend zamknął uruchomiony przez tester serwer.
