"""Held-out paraphrases are deliberately absent from the model context examples."""
CASES = [
 ('ustaw temperaturę na 30 stopni', 'set_temperature', {'value_c':30}),
 ('ustaw temperaturę', 'error', {}),
 ('ustaw pierwszą łopatkę na 40 stopni', 'set_polarization_angle', {'paddle':1,'angle_deg':40}),
 ('ustaw pierwszą łopatkę', 'error', {}),
 ('ustaw łopatkę na 40 stopni', 'error', {}),
 ('ustaw obie łopatki na 100 stopni', 'set_polarization_angle', {'paddle':'both','angle_deg':100}),
 ('przesuń obie łopatki o 5 stopni', 'move_polarization', {'paddle':'both','delta_deg':5}),
 ('ustaw piezo na 20 V', 'set_piezo_voltage', {'value_v':20}),
 ('ustaw piezo', 'error', {}),
 ('odpal grzanie', 'heater_on', {}),
 ('po co zmieniamy polaryzację w tym ćwiczeniu?', 'answer', {}),
 ('daj pierwszą na 35 stopni', 'set_polarization_angle', {'paddle':1,'angle_deg':35}),
 ('drugą przestaw o trzy stopnie', 'move_polarization', {'paddle':2,'delta_deg':3}),
 ('zacznij zbierać dane', 'start_measurement', {}),
 ('puść grzanie', 'heater_on', {}),
 ('daj dwadzieścia volt na piezo', 'set_piezo_voltage', {'value_v':20}),
]


def expected(action, args):
 if action == 'answer': return {'type':'answer','answer':'Wiedza ogólna: polaryzacja wpływa na sygnał.','steps':[]}
 if action == 'error': return {'type':'error','message':'Podaj brakujący parametr.','steps':[]}
 return {'type':'procedure','answer':'','steps':[{'action':action,'args':args}]}


def matches(result, action, args):
 return result.get('type') == action if action in {'answer','error'} else result == expected(action,args)
