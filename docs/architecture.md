# Architektura

Kod aplikacji jest rozdzielony na niewielką warstwę globalną i samodzielne
moduły urządzeń. `MainWindow` układa widoki, `ApplicationController` składa
aplikację, `PortManager` zapobiega współdzieleniu portu, a standardowy
`logging` przekazuje rekordy do konsoli i GUI bezpiecznym sygnałem Qt.

TC200 ma trzy warstwy:

1. `panel.py` emituje wyłącznie intencje użytkownika i prezentuje stan;
2. `controller.py` zawiera kontroler oraz jedynego workera w dedykowanym
   `QThread`;
3. `driver.py` implementuje synchroniczny protokół RS232 bez zależności od Qt.

Worker jest jedynym właścicielem drivera. Timer odczytu powstaje i działa w jego
wątku. Zamknięcie zatrzymuje timer, wielokrotnie bezpiecznie zamyka port, kończy
wątek i zwalnia rezerwację.

Parametry oraz komendy oparto na starym działającym kodzie gałęzi `main` i
instrukcji Thorlabs TC200 Rev G: 115200, 8N1, bez kontroli przepływu, komendy
małymi literami zakończone CR oraz odpowiedź zakończona promptem `>`.
