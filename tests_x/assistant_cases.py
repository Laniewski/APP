"""Frozen semantic expectations, independent of parser and model."""
P, A, T = 'set_piezo_voltage', 'set_polarization_angle', 'set_temperature'
U = ('unsupported', {})
LONG = 'rozpocznij pomiar ustaw temerature na 20 stopni wlacz grzalke poczekaj 30 s ustaw lopatke 1 ustaw piezo na 50v ustaw lopatki na 100 ustaw temerature na 30 stopni wlacz grzalke ustaw lopatki zakoncz pomiar zapisz plik'
CASES = [
 ('A', 'Ustaw piezo na 12 V.', [(P, {'value_v': 12})]),
 ('B', 'Ustaw piezo.', [(P, {'value_v': None})]),
 ('C', 'Ustaw drugą łopatkę.', [(A, {'paddle': 2, 'angle_deg': None})]),
 ('D', 'Ustaw drugą łopatkę na 30 stopni.', [(A, {'paddle': 2, 'angle_deg': 30})]),
 ('E', 'Ustaw temperaturę na 37 stopni i rozpocznij pomiar.', [(T, {'value_c': 37}), ('start_measurement', {})]),
 ('F', 'Włącz grzałkę.', [U]),
 ('G', 'Zapisz plik.', [U]),
 ('H', 'Ustaw piezo na 50 V i włącz grzałkę.', [(P, {'value_v': 50}), U]),
 ('I', 'Ustaw łopatkę 1, potem piezo na 50 V, potem łopatki na 100.', [(A, {'paddle': 1, 'angle_deg': None}), (P, {'value_v': 50}), (A, {'paddle': 1, 'angle_deg': 100}), (A, {'paddle': 2, 'angle_deg': 100})]),
 ('J', 'Ustaw pierwszą łopatkę na 20, drugą na 40.', [(A, {'paddle': 1, 'angle_deg': 20}), (A, {'paddle': 2, 'angle_deg': 40})]),
 ('K', 'Ustaw pierwszą łopatkę, drugą na 40.', [(A, {'paddle': 1, 'angle_deg': None}), (A, {'paddle': 2, 'angle_deg': 40})]),
 ('L', LONG, [('start_measurement', {}), (T, {'value_c': 20}), U, ('wait', {'seconds': 30}), (A, {'paddle': 1, 'angle_deg': None}), (P, {'value_v': 50}), (A, {'paddle': 1, 'angle_deg': 100}), (A, {'paddle': 2, 'angle_deg': 100}), (T, {'value_c': 30}), U, (A, {'paddle': 1, 'angle_deg': None}), (A, {'paddle': 2, 'angle_deg': None}), ('stop_measurement', {}), U]),
]

# Held-out phrasing: expectations describe the user's intent, not grammar coverage.
HOLDOUT = [
 ('M', 'Daj 12 V na piezo.', [(P, {'value_v': 12})]),
 ('N', 'Zacznij rejestrować dane.', [('start_measurement', {})]),
 ('O', 'Ustaw temperaturkę na 22 stopnie.', [(T, {'value_c': 22})]),
 ('P', 'Ustaw piezo na dwanaście V.', [(P, {'value_v': 12})]),
]
