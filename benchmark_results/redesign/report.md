# Przebudowa lokalnego planowania APP v2

Gałąź: `architecture-v2-learning`. Wykonanie AI pozostaje domyślnie OFF.
Nie uruchamiano fizycznych TC200, MDT694B, MPC220 ani ADS1263. Benchmark korzystał
wyłącznie z lokalnego modelu, a testy wykonania z fake controllerów.

## Diagnoza i decyzja

Główny problem nie był błędem JSON. Poprawny typ i dopuszczalny zakres nie dowodzą,
że liczba pochodzi z właściwej operacji. Dotychczasowy walidator przyjmował 35°
dla „Ustaw drugą łopatkę”, ponieważ 35 mieści się w zakresie. Model miał ponadto
zamkniętą listę akcji bez `unsupported` w krokach. Musiał zachować nieobsługiwaną
czynność w mało naturalnym polu `missing_parameters` albo pomijał/zastępował ją.

Dodatkowe problemy: rozbudowane opisy/title/notes, limit 400 tokenów na cały plan,
przykład 35° jako atrakcyjna wartość do kopiowania oraz benchmark dopasowujący
powtarzane akcje do najbliższych wartości zamiast do ich wystąpienia w kolejności.

Wybrałem częściową przebudowę warstwy planowania. Deterministyczne wykonanie,
Runner i MeasurementActions pozostały. ScriptBuilder wymagał małego uszczelnienia:
nie ufa przekazanemu pozytywnemu wynikowi walidacji i usuwa stary script.py przy
zastąpieniu planu niewykonywalnym.

**To jest konserwatywny interpreter wspomagany LLM. Nie jest uniwersalnym parserem
polszczyzny.** Plan końcowy pochodzi z ograniczonej gramatyki. Wynik LLM jest
porównywany i archiwizowany, ale nie rozszerza dozwolonego języka wykonywania.
Dzięki temu omyłka modelu nie może przenieść napięcia do grzałki. Kosztem są
fałszywe `unsupported` dla części poprawnych parafraz oraz koszt pomocniczej
inferencji nawet tam, gdzie gramatyka wystarcza. Nie przypisuję tych zabezpieczeń
„lepszemu rozumieniu” modelu.

## Przepływ i kontrakt

```text
USER
 → segmentacja całego polecenia z indeksami oryginalnego tekstu
 → małe partie ekstrakcji LLM: {steps:[{id, action, args}]}
 → porównanie z deterministyczną interpretacją każdego fragmentu
 → plan z request, source, null i unsupported
 → niezależny PlanValidator (ponownie sprawdza pochodzenie i wartości)
 → podgląd / zapis
 → APP_AI_EXECUTION_ENABLED + zatwierdzenie w GUI
 → ScriptBuilder → Runner → MeasurementActions → istniejące kontrolery
```

Model nie generuje Pythona. Nie ma dostępu do serial/USB. Nie ustala runnable.
`missing_parameters` wyznaczamy z argumentów null. Title jest stały, description
kopiuje źródło, notes dokumentuje rozbieżność ekstrakcji. Oryginalny wynik modelu
nie jest nadpisywany przez korektę planu.

```json
{
  "title": "Plan procedury",
  "request": "Ustaw piezo.",
  "steps": [{"description": "Ustaw piezo", "action": "set_piezo_voltage",
             "args": {"value_v": null}, "source": [0, 11]}],
  "missing_parameters": [], "notes": []
}
```

`source` to przedział [start,end) znaków Pythona w request, nie tokeny ani bajty.
Walidator odtwarza również kolejność i opisy; samo wystąpienie liczby gdziekolwiek
w wiadomości nie wystarcza. Dwa kroki łopatek mogą mieć ten sam source, ponieważ
jawnie rozwijają jedno polecenie w liczbie mnogiej.

| Polecenie | Reprezentacja | Wynik |
|---|---|---|
| Ustaw piezo na 12 V | value_v=12 | COMPLETE |
| Ustaw piezo | value_v=null | INCOMPLETE, bez skryptu |
| Ustaw drugą łopatkę | paddle=2, angle_deg=null | INCOMPLETE |
| Włącz grzałkę | action=unsupported, args={} | INVALID, bez skryptu |
| Zapisz plik | action=unsupported, args={} | INVALID |
| Ustaw drugą łopatkę na 200 | angle_deg=200 | INVALID: zakres |

`unsupported` oznacza brak narzędzia **lub brak bezpiecznego rozpoznania tekstu**.
Nie dodano wykonywalnej akcji o tej nazwie. Liczba mnoga „łopatki” oznacza obie
znane łopatki, w kolejności 1,2. Jednostki domyślne są jawnie częścią kontraktu:
C, V, stopnie, sekundy. Jawne inne jednostki nie są automatycznie przeliczane.

## Prompt, model i zasoby

Usunięto wszystkie few-shot i BAD/WHY/CORRECT, w tym 35°. Nie zastąpiono ich
placeholderami: mały model nadal musiałby rozwiązywać dodatkowe zadanie.
Zachowano znaczenia narzędzi, null, jednostki i aliasy numerów łopatek.
Enum id jest ograniczony do aktualnej partii, żeby model nie odwoływał się do
fragmentów z innego wywołania. Jedna naprawa dotyczy struktury JSON; pominięcie
czynności jest rozbieżnością semantyczną rozwiązywaną przy porównaniu ze źródłem.

| Część | Tokeny |
|---|---|
| Stary prompt razem | 1132 |
| Reguły | 312 |
| Definicje narzędzi | 534 |
| Przykłady | 194 |
| Antyprzykłady | 76 |
| Nowy prompt razem | 448 |

Tokeny mierzone endpointem `/tokenize` tego samego llama-server; narzut szablonu
czatu jest dodatkowy i widoczny w usage.prompt_tokens. Stary prompt zostawiał
916 tokenów na wiadomość użytkownika, narzut czatu i odpowiedź, z czego limit
odpowiedzi wynosił 400. Nowa odpowiedź nie zawiera prozy; duży plan jest dzielony
na partie po trzy fragmenty. Limit 400 tokenów obowiązuje każdą partię.

Pozostaję przy **Qwen3.5-2B Q4_K_M** już obecnym w cache. Nie pobrałem modeli.
Domyślna konfiguracja wybiera ten plik lokalnie; APP_AI_MODEL nadal pozwala wybrać
inny. CPU, 3 wątki, 2048 kontekstu, jeden slot, brak projektora i reasoning.
Nie porównywałem ponownie Qwen2.5-1.5B; nie ma podstaw do twierdzenia, że inny
model rozwiąże problem wiązania wartości. Oficjalna [karta Qwen3.5-2B](https://huggingface.co/Qwen/Qwen3.5-2B)
opisuje tryb bez myślenia jako domyślny i ostrzega przed pętlami w trybie myślenia.

Komenda użyta w pomiarze:
```sh
~/.local/share/app-v2/llama.cpp/build/bin/llama-server \
  -m ~/.cache/huggingface/hub/models--openresearchtools--Qwen3.5-2B-GGUF/snapshots/bc61fcb1c3ca790d262a25e721ddb597352954a9/Qwen3.5-2B-Q4_K_M.gguf \
  --host 127.0.0.1 --port 18767 -c 2048 -t 3 -b 256 -ub 128 \
  --cache-ram 0 -ngl 0 --parallel 1 --no-mmproj --reasoning off
```

## Testy i benchmark

Bazowe testy asystenta przed zmianą: **42/42 OK**. Po zmianie: **57/57 testów
asystenta OK** (42 dotychczasowe i 15 nowych). Pełne discovery: **140/141 OK**.
Jedyna porażka: `test_button_is_between_port_controls_and_paddle_panels`
w `tests_x/test_polarization_optimizer.py:49`. Test oczekuje przycisku pod indeksem
layoutu, pod którym znajduje się layout. Odtworzono także osobno; panel MPC220
i ten test są niezmienione. To nie jest zielona pełna seria i nie ukrywam tego.
Kompilacja modułu i benchmarku oraz `git diff --check` dla zmienionych plików: OK.
Kontrolę JSON Schema uruchomiono z istniejącym systemowym pakietem jsonschema:

```sh
PYTHONPATH=/usr/lib/python3/dist-packages .venv/bin/python -m unittest discover -s tests_x
```

Zapis wyników: test_results.txt. Bez systemowego jsonschema jeden opcjonalny test
kontraktu jest pomijany; aplikacja nie otrzymała nowej zależności runtime.

Stare raporty pozostają niezmienione: przed null 11/14, po null 13/14 pełnych
planów. Ponowna ocena zapisanych odpowiedzi z uwzględnieniem kolejności wystąpień
potwierdziła te liczby. Deterministyczny replay nowej gramatyki na tych samych
14 poleceniach daje 14/14; **to nie jest nowy pomiar inferencji modelu**.

Nowe porównanie A–L korzysta z tych samych oczekiwań przed/po. Oczekiwanie L
zapisano w design.md przed implementacją. Każdy przypadek ma jedną próbę, poza
maksymalnie jedną naprawą formatu na partię. Serwer może ponownie wykorzystać
cache prefiksu. To test regresji, nie dowód niezawodności statystycznej.

Metryki: rozpoznanie akcji używa liczności nazw, kolejność porównuje listę nazw,
wiązanie argumentów porównuje konkretny indeks wystąpienia i klucz. Zamiana
wartości między identycznymi nazwami akcji psuje wiązanie, nawet gdy kolejność
nazw pozostaje taka sama. Brakujący argument wymaga jawnego null. Recall i false
positive unsupported są oceniane na indeksach; braki/dodatkowe kroki oddzielnie.
Raport agreguje średnie po przypadkach z określoną metryką; brak mianownika to
null, nie 100%. JSON i schema są oddzielone od semantycznego INVALID.

| Metryka (A–L) | BEFORE | AFTER final |
|---|---:|---:|
| Rozpoznanie akcji | 64.6% | 100.0% |
| Kolejność akcji | 50.0% | 100.0% |
| Wiązanie argumentów | 73.2% | 100.0% |
| Brakujące argumenty | 40.0% | 100.0% |
| Unsupported recall | 0.0% | 100.0% |
| Unsupported false positives | 0.0% | 0.0% |
| Wymyślone akcje | 22.7% | 0.0% |
| Wymyślone/błędnie przypisane parametry | 22.7% | 0.0% |
| Pominięte akcje | 35.4% | 0.0% |
| Poprawność JSON | 91.7% | 100.0% |
| Poprawność schema | 91.7% | 100.0% |
| Poprawny COMPLETE/INCOMPLETE/INVALID | 50.0% | 100.0% |
| Pełny sukces semantyczny | 41.7% | 100.0% |
| Średni czas [s] | 34.39 | 26.82 |
| Średnia suma tokenów promptu | 1167.92 | 629.58 |
| Średnia suma tokenów wyjścia | 174.50 | 108.42 |
| Średnia szybkość dekodowania [tok/s] | 5.86 | 4.98 |

| Przypadek | BEFORE: sukces | AFTER: sukces | AFTER: stan |
|---|---|---|---|
| A | tak | tak | COMPLETE |
| B | tak | tak | INCOMPLETE |
| C | nie | tak | INCOMPLETE |
| D | tak | tak | COMPLETE |
| E | tak | tak | COMPLETE |
| F | nie | tak | INVALID |
| G | nie | tak | INVALID |
| H | nie | tak | INVALID |
| I | nie | tak | INCOMPLETE |
| J | tak | tak | COMPLETE |
| K | nie | tak | INCOMPLETE |
| L | nie | tak | INVALID |

Surowa ekstrakcja nowego modelu: **7/12** pełnych sukcesów, przed korektą
deterministyczną. Końcowy plan: **12/12**.
To oddzielne wyniki. Szczegółowe raw_score i oryginalne odpowiedzi są w after_final.json.
Długi test końcowy trwał **120.60 s**, obejmował 4 wywołania,
518 tokenów wyjścia i 2098 tokenów promptu łącznie.
Stary długi test zakończył się błędnym, obciętym JSON po 78.22 s.
Porównanie czasów nie oznacza równoważnej pracy: nowy wariant kończy pełny plan,
a stary urywa odpowiedź. Wyniki szybkości zależą od cache i obciążenia Pi.


Pierwszy przebieg nowej wersji zachowano w after.json. W przypadku I integracja
błędnie traktowała brak id jako błąd formatu i przerwała po retry. Naprawiono
rozróżnienie struktury i semantyki. W tym przebiegu model gubił też znaczenie
„drugą”; uzupełniono aliasy argumentu. Finalny przebieg ma osobny plik, aby nie
ukrywać wcześniejszych błędów. Pierwszy pomiar A w after.json obejmował oczekiwanie
na zajęty serwer; do głównej tabeli użyto osobnego finalnego przebiegu.

Mała ablacja dotyczyła C, H i L: stary prompt z przykładami **0/3**, stary prompt
bez przykładów i antyprzykładów **0/3** pełnych sukcesów. Bez przykładów C otrzymał
wymyślone 45°; H nadal błędnie interpretował grzałkę; L zakończył się obciętym JSON.
Usunięcie przykładów samo nie naprawia semantyki. Nie wykonano osobnej konfiguracji
z „kilkoma” przykładami: trzy warianty (stary, bez przykładów, przebudowany) już
pokazały, że zasadniczy efekt pochodzi z walidacji źródła, nie liczby demonstracji.
Ze względu na różne zadania i liczbę wywołań przebudowanego wariantu nie jest to
czysta ablacja samego promptu.

**Regresja językowa: oddzielne M–P mają 4/4 sukcesy starego modelu i 0/4 końcowych
sukcesów nowej warstwy.** Wszystkie cztery są bezpiecznie zablokowane, ale to
fałszywe unsupported, nie poprawna interpretacja intencji.

| Parafraza | Oczekiwanie | Wynik końcowy po zmianie |
|---|---|---|
| Daj 12 V na piezo. | piezo 12 V | unsupported / INVALID |
| Zacznij rejestrować dane. | start_measurement | unsupported / INVALID |
| Ustaw temperaturkę na 22 stopnie. | temperatura 22°C | unsupported / INVALID |
| Ustaw piezo na dwanaście V. | piezo 12 V | unsupported / INVALID |

Nie zmieniono oczekiwań ani gramatyki, żeby poprawić tę tabelę. Fałszywie dodatnie
unsupported w tej grupie wynosi 100%. Wyniku A–L nie wolno przedstawiać jako
100% skuteczności dla swobodnej polszczyzny. Te parafrazy mierzą koszt konserwatywnego
projektu; kolejny etap musi rozszerzyć i niezależnie przetestować pokrycie językowe.

## Dokładny długi acceptance test

```text
rozpocznij pomiar ustaw temerature na 20 stopni wlacz grzalke poczekaj 30 s ustaw lopatke 1 ustaw piezo na 50v ustaw lopatki na 100 ustaw temerature na 30 stopni wlacz grzalke ustaw lopatki zakoncz pomiar zapisz plik
```

| Krok | Akcja | Argumenty |
|---|---|---|
| 1 | start_measurement | {} |
| 2 | set_temperature | value_c=20 |
| 3 | unsupported | włącz grzałkę |
| 4 | wait | seconds=30 |
| 5 | set_polarization_angle | paddle=1, angle_deg=null |
| 6 | set_piezo_voltage | value_v=50 |
| 7 | set_polarization_angle | paddle=1, angle_deg=100 |
| 8 | set_polarization_angle | paddle=2, angle_deg=100 |
| 9 | set_temperature | value_c=30 |
| 10 | unsupported | włącz grzałkę |
| 11 | set_polarization_angle | paddle=1, angle_deg=null |
| 12 | set_polarization_angle | paddle=2, angle_deg=null |
| 13 | stop_measurement | {} |
| 14 | unsupported | zapisz plik |

Wynik: INVALID; trzy czynności unsupported i trzy pytania o kąty. Piezo 50 V
występuje tylko w kroku 6. Późniejsze 100° nie uzupełnia kroku 5 ani kroków 11–12.
Pełny JSON wraz z indeksami źródła zapisano jako acceptance_plan.json.

## Pliki

| Plik | Zmiana |
|---|---|
| modules/measurement_assistant/grounding.py | Nowy: segmentacja, ograniczona pełna gramatyka, źródła, rozwijanie obu łopatek, porównanie planu z request |
| modules/measurement_assistant/backend.py | Partie ekstrakcji, retry struktury, archiwum odpowiedzi, porównanie z gramatyką, metryki wszystkich prób, anulowanie między partiami, log serwera w runs |
| modules/measurement_assistant/context_builder.py | Krótki prompt bez przykładów; schema ekstrakcji z id i unsupported; aliasy liczb porządkowych |
| modules/measurement_assistant/config.py | Domyślny zainstalowany Qwen3.5-2B; bez pobierania; gate pozostaje false |
| modules/measurement_assistant/plan_schema.py | Jawne unsupported, request/source, weryfikacja pochodzenia, typów indeksów i zgodności ze źródłem |
| modules/measurement_assistant/script_builder.py | Ponowna walidacja przy zapisie, usunięcie nieaktualnego skryptu przy zmianie planu |
| modules/measurement_assistant/panel.py | Kopiowanie finalnego planu zamiast surowej ekstrakcji |
| tests_x/assistant_cases.py | Nowy: oczekiwania A–L i oddzielne parafrazy M–P |
| tests_x/benchmark_assistant_grounding.py | Nowy: porównania, osobne metryki, raw_score, limity/retry w statystykach, zapisy każdego przypadku |
| tests_x/benchmark_measurement_assistant_models.py | Nowy punkt wejścia benchmarku; stare CASES zachowane; koniec dopasowywania do najbliższych wartości |
| tests_x/test_assistant_grounding.py | Nowy: semantyka, źródła, negacje, warunki, jednostki, podmiany, schema, blokady skryptu, pominięcia LLM |
| tests_x/test_measurement_assistant.py | Aktualizacja kontraktu mocków i wcześniejszego testu przyjmującego wymyślony kąt; testy wykonania nadal na fake |
| docs/measurement_assistant.md | Nowa dokumentacja konfiguracji, kontraktu, przepływu i ograniczeń |
| benchmark_results/redesign/ | Nowe snapshoty promptów/schema, surowe odpowiedzi, porównania, diagnoza i ten raport |

Nie usunięto plików. actions.py, controller.py, runner.py i sterowniki sprzętowe
pozostają bez zmian. Nie zmieniano pliku użytkownika `xxxxx` ani starego katalogu
wyników null/before_null_contract.

## Ograniczenia i dalsza praca

- Nieznane parafrazy, część literówek, złożone liczebniki, warunki, pętle i inne
  jednostki są blokowane. `unsupported` nie rozróżnia jeszcze braku narzędzia
  od zbyt wąskiej gramatyki. Potrzebny jest wygodny proces doprecyzowania.
- Nie ma stabilizacji, heater_on, zapisu pliku, maila ani sweep. Nie dodawano
  fikcyjnych narzędzi. Ich przyszłe wykonanie powinno być deterministyczne.
- Jednostki domyślne oraz rozwijanie obu łopatek są nową, jawną polityką; użytkownik
  powinien sprawdzić podgląd przed ewentualnym wykonaniem.
- Limit wejścia nie jest matematyczną gwarancją zmieszczenia każdej egzotycznej
  tokenizacji w 2048. Błąd transportu lub dwukrotnie błędny JSON zatrzymuje planowanie.
- Walidacja napięcia MDT694B nadal zależy od efektywnego zakresu odczytanego przez
  istniejący driver. COMPLETE nie jest gwarancją połączenia urządzeń ani powodzenia
  procedury w aktualnym stanie sprzętu.
- Dla zgodności pozostawiono stare plany bez request/source. Walidacja takiego
  planu bez osobno przekazanego polecenia sprawdza tylko strukturę i zakresy.
  Nowy backend zawsze zapisuje źródło; nie należy omijać go, przekazując surowy
  wynik LLM bezpośrednio do ScriptBuilder/Runner.
- Samo pole request w pliku nie jest podpisem kryptograficznym. Zmienianie równocześnie
  całego planu i źródła przez lokalnego użytkownika wykracza poza obronę przed błędem LLM.
- Pomocniczy LLM kosztuje czas również dla jednoznacznych poleceń. Następny rozsądny
  eksperyment to opcjonalna szybka ścieżka bez inferencji dla w pełni rozpoznanej
  gramatyki oraz użycie modelu do proponowania doprecyzowań dla reszty.

### Co zrobiłem

Przebudowałem warstwę planowania i benchmark, zachowałem deterministyczne wykonanie,
wprowadziłem źródła, null i jawne unsupported, uruchomiłem lokalny model oraz testy.

### Co poprawiło wyniki

Pełne dopasowanie każdego fragmentu i niezależne odtworzenie argumentów ze źródła.
Mniejszy prompt redukuje koszt prozy; sam prompt nie zapewnia bezpieczeństwa.

### Co nadal może się zepsuć

Rozpoznanie nietypowego języka, segmentacja, ekstrakcja małego modelu i dostępność
serwera. Oczekiwaną reakcją jest blokada lub prośba o doprecyzowanie, nie zgadywanie.

### Co zrobiłbym jako następny krok

Zebrałbym rzeczywiste anonimowe polecenia, rozdzielił błędy gramatyki od braku
narzędzi, dodał doprecyzowania w GUI i zmierzył szybkie planowanie bez zbędnej
inferencji. Nie włączałbym automatycznego wykonania na podstawie samego benchmarku.
