"""Conservative full-match grammar. Unknown text remains non-executable."""
import re
import unicodedata


def fold(text):
    return ''.join(c for c in unicodedata.normalize('NFD', text.lower().replace('ł', 'l')) if unicodedata.category(c) != 'Mn')


VERBS = r'ustaw|nastaw|rozpocznij|zacznij|zatrzymaj|zakoncz|poczekaj|odczekaj|wlacz|wylacz|zapisz|wyslij|uruchom'
BOUNDARY = re.compile(r'(?<!\d)[,.;\n]+|[,;\n]+(?!\d)|\b(?:i|a potem|potem|nastepnie)\b|(?<!\w)(?=(?:' + VERBS + r')\b)')


def segments(request):
    normalized = fold(request)
    if len(normalized) != len(request):
        return [(0, len(request), request)]
    cuts = {0, len(request)}
    for match in BOUNDARY.finditer(normalized):
        if match.start() == match.end() and re.search(r'\b(?:nie|jesli|gdy)\s*$', normalized[:match.start()]):
            continue
        cuts.update((match.start(), match.end()))
    spans = []
    ordered = sorted(cuts)
    for start, end in zip(ordered, ordered[1:]):
        text = request[start:end]
        if fold(text).strip(' ,.;\n\t') in {'', 'i', 'potem', 'a potem', 'nastepnie', 'najpierw'}:
            continue
        spans.append((start, end, text))
    return spans


WORDS = {'zero': 0, 'jeden': 1, 'dwa': 2, 'trzy': 3, 'cztery': 4, 'piec': 5,
         'szesc': 6, 'siedem': 7, 'osiem': 8, 'dziewiec': 9,
         'dziesiec': 10, 'dwadziescia': 20, 'trzydziesci': 30,
         'czterdziesci': 40, 'piecdziesiat': 50, 'szescdziesiat': 60,
         'siedemdziesiat': 70, 'osiemdziesiat': 80, 'dziewiecdziesiat': 90, 'sto': 100}
NUM = r'[+-]?\d+(?:[.,]\d+)?|' + '|'.join(WORDS)
VALUE = r'(?P<value>(?:' + NUM + r'))'


def number(value):
    if value is None:
        return None
    return WORDS[value] if value in WORDS else float(value.replace(',', '.'))


def interpret(text, previous_polarization=False):
    t = re.sub(r'\s+', ' ', fold(text).strip(' ,.;\n\t'))
    t = re.sub(r'^(?:prosze\s+)?(?:ustaw|nastaw)\s+', '', t)
    for pattern, action in [(r'(?:rozpocznij|zacznij) pomiar', 'start_measurement'),
                            (r'(?:zatrzymaj|zakoncz) pomiar', 'stop_measurement')]:
        if re.fullmatch(pattern, t):
            return [(action, {})]
    scalar = [
        (r'tem(?:pera|era)ture', 'set_temperature', 'value_c', r'(?:stopni(?: celsjusza)?|°c|c)'),
        (r'(?:plytke |napiecie |kontroler )?piezo', 'set_piezo_voltage', 'value_v', r'(?:v|wolt(?:ow|y)?)'),
        (r'(?:poczekaj|odczekaj)', 'wait', 'seconds', r'(?:s|sekund(?:y|e)?)'),
    ]
    for noun, action, key, unit in scalar:
        m = re.fullmatch(noun + r'(?:\s+(?:na\s+)?' + VALUE + r'\s*(?:' + unit + r')?)?', t)
        if m:
            return [(action, {key: number(m['value'])})]
    selector = r'(pierwsza|pierwszy|druga|drugi)'
    noun = r'(?:lopatke(?: polaryzacji)?|nastawnik polaryzacji)'
    m = re.fullmatch(r'(?:(?P<ordinal>' + selector + r')\s+' + noun + r'|' + noun + r'(?:\s+(?P<index>[12]))?|(?P<plural>lopatki|obie lopatki))' + r'(?:\s+na\s+' + VALUE + r'\s*(?:stopni|°)?)?', t)
    if m:
        paddle = int(m['index']) if m['index'] else (1 if m['ordinal'] and m['ordinal'].startswith('pierwsz') else 2 if m['ordinal'] else None)
        paddles = [1, 2] if m['plural'] else [paddle]
        return [('set_polarization_angle', {'paddle': p, 'angle_deg': number(m['value'])}) for p in paddles]
    if previous_polarization:
        m = re.fullmatch(r'(?P<ordinal>' + selector + r')(?:\s+na\s+' + VALUE + r'\s*(?:stopni|°)?)?', t)
        if m:
            return [('set_polarization_angle', {'paddle': 1 if m['ordinal'].startswith('pierwsz') else 2, 'angle_deg': number(m['value'])})]
    return [('unsupported', {})]


def grounded_plan(request):
    steps = []
    previous = False
    for start, end, text in segments(request):
        actions = interpret(text, previous)
        for action, args in actions:
            steps.append({'description': text.strip(), 'action': action, 'args': args,
                          'source': [start, end]})
        previous = actions[-1][0] == 'set_polarization_angle'
    return {'title': 'Plan procedury', 'steps': steps, 'missing_parameters': [],
            'notes': [], 'request': request}


def grounding_errors(plan, request):
    expected = grounded_plan(request)['steps']
    actual = plan.get('steps', [])
    if not isinstance(actual, list):
        return ['Nieprawidłowa lista kroków.']
    signature = lambda rows: [(s.get('action'), s.get('args'), s.get('source'), s.get('description')) for s in rows if isinstance(s, dict)]
    if signature(actual) != signature(expected):
        return ['Akcje, argumenty lub źródła nie odpowiadają poleceniu; wymagane ponowne planowanie.']
    return []
