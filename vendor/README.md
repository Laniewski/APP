# Vendor code

Ten katalog zawiera niskopoziomowy kod producentów, który będzie wykorzystywany przez nowe sterowniki urządzeń.

- `vendor/waveshare/`: sterownik ADS1263 i pomocniczna konfiguracja sprzętowa Waveshare.
- `vendor/thorlabs_apt_protocol/`: biblioteka Thorlabs APT do komunikacji z MPC220.

Kod w `vendor/` nie jest częścią nowej aplikacji GUI i nie jest importowany podczas uruchamiania obecnej wersji `APPv2`.
Nowa aplikacja będzie używać tego kodu tylko w przyszłych sterownikach urządzeń.
