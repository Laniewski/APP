# APPv2

Modułowa aplikacja PySide6 do obsługi stanowiska laboratoryjnego. Na obecnym
etapie zaimplementowany jest wyłącznie kontroler temperatury Thorlabs TC200.
Katalogi MDT694B, MPC220 i pomiarów są celowo puste.

## Struktura

- `main.py` — utworzenie aplikacji i bezpieczne zamknięcie;
- `app/` — główne okno, kontroler aplikacji, logowanie i zarządzanie portami;
- `modules/tc200/` — panel, kontroler z workerem oraz sterownik protokołu;
- `modules/{mdt694b,mpc220,measurement}/` — miejsca na przyszłe moduły;
- `vendor/` — zachowane biblioteki producentów;
- `tests/` — testy bez fizycznego urządzenia;
- `docs/` — dokumentacja projektu.

Przepływ TC200: `TC200Panel → TC200Controller → TC200Worker (QThread) →
TC200Driver → port szeregowy`. Odpowiedzi wracają do GUI sygnałami Qt.

## Instalacja i uruchomienie

Wymagany jest Python 3.10 lub nowszy.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```

Testy nie wymagają podłączonego sprzętu:

```bash
python -m unittest discover -v
```

## Zakres TC200

Aplikacja skanuje i rezerwuje porty, identyfikuje TC200 przez `*idn?`, odczytuje
temperaturę bieżącą i zadaną, ustawia temperaturę 20,0–200,0°C, przełącza
grzanie, interpretuje status i alarmy oraz okresowo odświeża dane. Operacje
szeregowe są wykonywane kolejno w dedykowanym wątku. Timeout, błędna odpowiedź,
inne urządzenie na porcie i zamknięcie aplikacji są obsługiwane bez blokowania
GUI.

## Pierwszy kontrolowany test ze sprzętem

1. Przy wyłączonym grzaniu połącz TC200 z Raspberry Pi przez właściwy adapter
   RS232/USB i uruchom TC200.
2. Uruchom aplikację, kliknij „Odśwież”, wybierz rozpoznany port i „Połącz”.
3. Potwierdź, że identyfikacja się powiodła, a temperatura, setpoint, status i
   alarmy są odświeżane.
4. Ustaw bezpieczną dla układu wartość niewiele wyższą od temperatury bieżącej.
5. Włącz grzanie na krótko, obserwuj wskazanie i wyłącz je.
6. Kliknij „Rozłącz”, ponownie połącz, a następnie zamknij aplikację podczas
   aktywnego połączenia i sprawdź, czy port został zwolniony.

Testy automatyczne potwierdzają protokół i zachowanie aplikacji z portem
symulowanym. Nie stanowią potwierdzenia działania z fizycznym TC200.
