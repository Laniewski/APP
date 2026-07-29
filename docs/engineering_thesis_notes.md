# Notatki do pracy inżynierskiej

## Cel projektu

## Architektura aplikacji

## Zastosowane urządzenia

## Komunikacja ze sprzętem

## System pomiarowy

## Kalibracja MPC220

## Problemy i rozwiązania

## Testy

## Wyniki

## Decyzje projektowe

- Stary kod zachowano jako referencję, aby uniknąć utraty sprawdzonych rozwiązań i w prosty sposób analizować istniejące sterowniki.
- Kod producentów oddzielono od kodu aplikacji, aby nowy GUI pozostał niezależny od niskopoziomowych bibliotek sprzętowych.
- GUI oddzielono od blokującej komunikacji sprzętowej, bo blokujące operacje muszą działać poza głównym wątkiem Qt.
- Urządzenia będą wdrażane pojedynczo, aby kolejno weryfikować ich działanie i unikać mieszania problemów sprzętowych.
- Usuwanie potencjalnie nieużywanych funkcji odłożono do migracji urządzeń lub końcowego audytu, aby zachować pełną referencję dla przyszłych implementacji.
