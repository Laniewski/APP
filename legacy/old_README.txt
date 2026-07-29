SZKIELET APLIKACJI

main.py          - tworzy obiekty i uruchamia program
main_window.py   - wyłącznie wygląd GUI
controller.py    - łączy przyciski z funkcjami

devices/         - osobna klasa dla każdego urządzenia
app/plot_manager.py   - wykres
app/system_control.py - operacje całego systemu
app/logger.py         - logi

Na tym etapie GUI działa, ale funkcje urządzeń są puste.

Uruchomienie na Windows:
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
