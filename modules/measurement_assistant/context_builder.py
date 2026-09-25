"""Small extraction contract, with no numerical demonstrations."""
import json
from .actions import ACTION_REGISTRY


def tool_definitions():
    return [spec.tool_definition() for spec in ACTION_REGISTRY.values()]


def planning_examples():
    return []


def system_prompt():
    tools = []
    for spec in ACTION_REGISTRY.values():
        tools.append({'action': spec.name, 'meaning': spec.description,
                      'args': {key: {'unit': arg.unit, 'nullable': arg.nullable,
                                     **({'choices': arg.choices, 'aliases': arg.choice_aliases} if arg.choices else {})}
                               for key, arg in spec.arguments.items()}})
    return (
        'Przepisz ponumerowane fragmenty polecenia na JSON {steps:[{id,action,args}]}. '
        'Zachowaj kolejność i id fragmentu. Każdą czynność zachowaj. '
        'Nieobsługiwana lub niejasna czynność: action=unsupported, args={}. '
        'Grzałka, zapis pliku, mail i stabilizacja są nieobsługiwane. '
        'Wartości bierz wyłącznie z danego fragmentu; brakujący wymagany argument zwróć jako null. '
        'Nie przenoś liczb między fragmentami. Łopatki w liczbie mnogiej oznaczają obie (1,2). '
        'Jednostki domyślne narzędzi: C, V, stopnie, sekundy. '
        'Bez opisów, tytułu, kodu i komentarzy. Narzędzia: '
        + json.dumps(tools, ensure_ascii=False, separators=(',', ':')))


def extraction_schema(ids=None):
    from .plan_schema import response_schema
    variants = response_schema()['properties']['steps']['items']['oneOf']
    for variant in variants:
        variant['required'] = ['id', 'action', 'args']
        variant['properties'].pop('description')
        variant['properties'].pop('source', None)
        variant['properties']['id'] = {'type': 'integer', 'minimum': 0}
        if ids is not None:
            variant['properties']['id']['enum'] = list(ids)
    return {'type': 'object', 'additionalProperties': False, 'required': ['steps'],
            'properties': {'steps': {'type': 'array', 'maxItems': 12, 'items': {'oneOf': variants}}}}
