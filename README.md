# APPv2

APPv2 to nowa wersja interfejsu GUI dla sterowania stanowiskiem laboratoryjnym. Obecnie aplikacja uruchamia samodzielne GUI w PySide6 bez komunikacji ze sprzętem.

## Aktualny etap projektu

- Nowy GUI działa niezależnie od podłączonych urządzeń.
- Stary kod aplikacji zachowano w `legacy/` jako referencję.
- Kod producentów znajduje się w `vendor/`.
- Następny etap to integracja TC200.

## Główna architektura

- `main.py` — uruchomienie aplikacji.
- `app/main_window.py` — nowy interfejs GUI.
- `devices/` — pakiet przyszłych sterowników urządzeń.
- `app/workers/` — punkt startowy dla workerów wykonujących operacje poza GUI.
- `legacy/` — stary kod aplikacji jako referencja.
- `vendor/` — kod producentów.
- `docs/` — dokumentacja architektury i notatki inżynierskie.

## Wymagania

- Python 3.13
- PySide6
- pyqtgraph

## Utworzenie środowiska

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Uruchomienie aplikacji

```bash
python main.py
```

## Ważne informacje

- Aplikacja nie wymaga urządzeń podłączonych do komputera, aby uruchomić GUI.
- Obecnie GUI nie realizuje rzeczywistej komunikacji z TC200, MDT694B, ADS1263 ani MPC220.
- Stare pliki aplikacji znajdują się w `legacy/`.
- Kod producentów znajduje się w `vendor/`.
