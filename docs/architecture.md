# Architektura APPv2

Nowa aplikacja APPv2 ma wyraźny podział odpowiedzialności:

- GUI: prezentuje dane użytkownikowi i przyjmuje polecenia.
- Kontroler: pośredniczy między GUI a workerami, tłumacząc akcje użytkownika na zadania.
- Workery: wykonują blokujące operacje sprzętowe poza głównym wątkiem Qt.
- Sterowniki urządzeń: implementują logikę obsługi TC200, MDT694B, ADS1263 i MPC220.
- Kod producentów: niskopoziomowe biblioteki Waveshare oraz Thorlabs APT w katalogu `vendor/`.
- Urządzenia fizyczne: TC200, MDT694B, ADS1263, MPC220.

Planowany przepływ komunikacji:

GUI → kontroler → worker → sterownik → vendor/urządzenie

Krótki opis roli warstw:

- GUI odpowiada za prezentację danych i działania użytkownika.
- Kontroler będzie łączył sygnały GUI z workerami.
- Operacje blokujące będą wykonywane poza głównym wątkiem.
- GUI może być modyfikowane wyłącznie w głównym wątku Qt.
- Workery będą komunikowały wyniki do GUI za pomocą sygnałów.
- Workery będą dodawane stopniowo.
- Pierwszym integrowanym urządzeniem będzie TC200.
- `MeasurementWorker` będzie później obsługiwał ciągły odczyt ADS1263.
- TC200, MDT694B, ADS1263 i MPC220 będą wdrażane pojedynczo.
- Stare sterowniki pozostają w `legacy/` jako referencja.
- Kod producentów znajduje się w `vendor/`.
- Nieusuwane funkcje będą oceniane podczas migracji urządzeń lub końcowego audytu.

Planowana kolejność dalszych prac:

1. TC200 — wybór portu → połączenie → odczyt temperatury → pierwszy worker.
2. MDT694B — nowy sterownik i sterowanie napięciem.
3. ADS1263 — warstwa pośrednia nad kodem Waveshare i ciągły pomiar dwóch kanałów.
4. MPC220 — ponowna analiza protokołu, testy ruchu i kalibracja.
5. Końcowy audyt nieużywanego kodu.
