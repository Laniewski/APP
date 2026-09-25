#!/usr/bin/env python3
"""Isolated, hardware-free benchmark of the current planning contract.

Only selected pure definitions are compiled from the current source AST. No
application modules, Qt classes, drivers, controllers or action executors load.
"""
import argparse
import ast
from collections import Counter
from dataclasses import dataclass, field
import hashlib
import json
import math
from pathlib import Path
import socket
import statistics
import subprocess
import sys
import time
from types import SimpleNamespace
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'modules/measurement_assistant'
LIMITATION = ('Current contract preserves incomplete actions with nullable arguments. '
              'PlanValidator derives missing questions independently of model declarations. '
              'Null is INCOMPLETE, never runnable; structural/range/type failures remain INVALID.')

def selected(path, names, namespace):
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    nodes = [n for n in tree.body if
             isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names or
             isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in names for t in n.targets)]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), namespace)
    return tree

def contract():
    ns = {'__name__': __name__, 'json': json, 'math': math,
          'dataclass': dataclass, 'field': field}
    driver = ast.parse((ROOT / 'modules/tc200/driver.py').read_text())
    cls = next(n for n in driver.body if isinstance(n, ast.ClassDef) and n.name == 'TC200Driver')
    constants = {t.id: ast.literal_eval(n.value) for n in cls.body if isinstance(n, ast.Assign)
                 for t in n.targets if isinstance(t, ast.Name) and t.id in {'MIN_TEMPERATURE', 'MAX_TEMPERATURE'}}
    ns['TC200Driver'] = SimpleNamespace(**constants)
    cal = ast.parse((ROOT / 'modules/mpc220/calibration.py').read_text())
    for n in cal.body:
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and t.id in {'MPC_MIN_ANGLE_DEG', 'MPC_MAX_ANGLE_DEG'}:
                    ns[t.id] = ast.literal_eval(n.value)
    selected(SOURCE / 'actions.py', {'ArgumentSpec', 'ActionSpec', 'ACTION_REGISTRY'}, ns)
    selected(SOURCE / 'plan_schema.py', {'ValidationResult', 'parse_response', 'PlanValidator',
             'STABILIZATION_MISSING', 'requires_unsupported_stabilization', 'response_schema'}, ns)
    selected(SOURCE / 'context_builder.py', {'tool_definitions', 'planning_examples', 'system_prompt'}, ns)
    tree = selected(SOURCE / 'backend.py', set(), ns)
    generate = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'generate')
    caps = [ast.literal_eval(v) for n in ast.walk(generate) if isinstance(n, ast.Dict)
            for k, v in zip(n.keys, n.values) if isinstance(k, ast.Constant) and k.value == 'max_tokens']
    if len(caps) != 1:
        raise RuntimeError('Cannot uniquely read backend max_tokens')
    return ns, caps[0]

P = 'set_piezo_voltage'
A = 'set_polarization_angle'
T = 'set_temperature'
CASES = [
    ('Ustaw piezo na 12 V.', [(P, {'value_v': 12})]),
    ('Ustaw piezo.', [(P, {'value_v': None})]),
    ('Ustaw drugą łopatkę na 30 stopni.', [(A, {'paddle': 2, 'angle_deg': 30})]),
    ('Ustaw drugą łopatkę.', [(A, {'paddle': 2, 'angle_deg': None})]),
    ('Ustaw temperaturę na 37 stopni i rozpocznij pomiar.', [(T, {'value_c': 37}), ('start_measurement', {})]),
    ('Poczekaj 4 sekundy i zatrzymaj pomiar.', [('wait', {'seconds': 4}), ('stop_measurement', {})]),
    ('Ustaw piezo na 20 V i drugą łopatkę na 45 stopni.', [(P, {'value_v': 20}), (A, {'paddle': 2, 'angle_deg': 45})]),
    ('Ustaw temperaturę.', [(T, {'value_c': None})]),
    ('Rozpocznij pomiar.', [('start_measurement', {})]),
    ('Ustaw pierwszą łopatkę na 25 stopni, potem drugą na 50 stopni.', [(A, {'paddle': 1, 'angle_deg': 25}), (A, {'paddle': 2, 'angle_deg': 50})]),
    ('Ustaw płytkę piezo na 15 V.', [(P, {'value_v': 15})]),
    ('Ustaw drugi nastawnik polaryzacji na 40 stopni.', [(A, {'paddle': 2, 'angle_deg': 40})]),
    ('Najpierw rozpocznij pomiar, potem ustaw piezo na 10 V.', [('start_measurement', {}), (P, {'value_v': 10})]),
    ('Ustaw piezo na 10.', None),
    ('Ustaw drugą łopatkę na dziewięćdziesiąt stopni.', [(A, {'paddle': 2, 'angle_deg': 90})]),
]

def evaluate(plan, expected, missing_questions=None):
    if expected is None:
        return dict(correct_actions=None, correct_order=None, correct_parameters=None,
                    missing_detected=None, hallucinated_parameter=None, full_plan_success=None,
                    observation='No asserted voltage unit; observational case excluded from semantic rates.')
    steps = plan.get('steps', []) if isinstance(plan, dict) else []
    steps = steps if isinstance(steps, list) else []
    actual = [(s.get('action'), s.get('args')) for s in steps if isinstance(s, dict)]
    executable = list(expected)
    names = [a for a, _ in actual]
    wanted = [a for a, _ in executable]
    missing = [(a, k) for a, args in expected for k, v in args.items() if v is None]
    qs = missing_questions if missing_questions is not None else (plan.get('missing_parameters', []) if isinstance(plan, dict) else [])
    question = ' '.join(q for q in qs if isinstance(q, str)).casefold() if isinstance(qs, (list, tuple)) else ''
    keywords = {'value_v': ('napi', 'voltage'), 'angle_deg': ('kąt', 'kat', 'angle'),
                'value_c': ('temperatur', 'temperature')}
    detected = all(any(word in question for word in keywords[k]) and
                   any(a == action and isinstance(args, dict) and key in args and args[key] is None
                       for a, args in actual)
                   for action, key in missing for k in [key]) if missing else None
    # Match repeated actions to their closest expected arguments; order scored separately.
    remaining = list(expected)
    hallucinated = False
    parameters = True
    for action, args in actual:
        candidates = [(i, e) for i, e in enumerate(remaining) if e[0] == action]
        if not isinstance(args, dict) or not candidates:
            parameters = False
            if isinstance(args, dict):
                hallucinated |= any(isinstance(v, (int, float)) and not isinstance(v, bool) for v in args.values())
            continue
        i, (_, known) = max(candidates, key=lambda x: sum(args.get(k) == v for k, v in x[1][1].items() if v is not None))
        remaining.pop(i)
        for key, value in args.items():
            if key not in known or known[key] is None:
                if value is not None: hallucinated = True; parameters = False
            elif isinstance(value, bool) or value != known[key]:
                parameters = False
                if isinstance(value, (int, float)): hallucinated = True
        for key, value in known.items():
            if value is not None and args.get(key) != value: parameters = False
    # Preserve incomplete actions with explicit null, per the new contract.
    parameters &= all(any(a == action and isinstance(args, dict) and args == wanted_args
                          for a, args in actual) for action, wanted_args in executable)
    if missing: parameters &= bool(detected) and not hallucinated
    elif qs: parameters = False
    return dict(correct_actions=Counter(names) == Counter(wanted), correct_order=names == wanted,
                correct_parameters=bool(parameters), missing_detected=detected,
                hallucinated_parameter=bool(hallucinated))

def request(url, payload=None, timeout=120):
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res: return json.load(res)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'HTTP {exc.code}: {exc.read().decode(errors="replace")}') from exc


def source_hashes():
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (list(SOURCE.glob('*.py')) + [ROOT / 'modules/tc200/driver.py', ROOT / 'modules/mpc220/calibration.py'])}


def report(data, path):
    scored = [r for r in data['tests'] if r['test'] != 14]
    missing = [r for r in scored if r['test'] in (2, 4, 8)]
    def rate(rows, key): return sum(r.get(key) is True for r in rows) / len(rows) if rows else 0
    metrics = {'action_accuracy': rate(scored, 'correct_actions'), 'parameter_accuracy': rate(scored, 'correct_parameters'),
               'missing_parameter_detection_accuracy': rate(missing, 'missing_detected'),
               'hallucination_rate': rate(scored, 'hallucinated_parameter'),
               'json_validity_rate': rate(data['tests'], 'valid_json'),
               'full_plan_success_rate': rate(scored, 'full_plan_success'),
               'mean_time_s': statistics.mean(r['time_s'] for r in data['tests']),
               'mean_tokens_s': statistics.mean([r['tokens_s'] for r in data['tests'] if r.get('tokens_s') is not None] or [0])}
    data['metrics'] = metrics
    lines = ['# Benchmark Qwen3.5-2B Q4_K_M', '',
             '15 pojedynczych prób; temperature=0, context=2048, threads=4, max_tokens='+str(data['max_tokens'])+'.',
             'Myślenie i projektor wyłączone. Brak wykonania sprzętowego. Surowe odpowiedzi bez napraw semantycznych.', '',
             '## Ograniczenia i sposób oceny', '', LIMITATION, '',
             'Requesty zachowują domyślne cache promptu backendu. Każda rozmowa jest niezależna, ale wspólny prefiks może być ponownie używany. Pierwszy request miał zimny cache promptu; timings zapisują cache_n i prompt_n dla każdej próby.', '',
             'Ocena akcji uwzględnia aktualny prompt: niekompletne akcje pozostają z null, a pytania wyznacza walidator. '
             'Oczekiwania użytkownika z null są zachowane w JSON jako expected_intent. '
             'validator_passed oznacza brak errors; runnable zapisane osobno i uwzględnia missing_parameters. '
             'Full-plan success wymaga poprawnych akcji, kolejności, parametrów, JSON, walidatora i wykrycia braków. '
             'Test 14 jest wyłącznie obserwacyjny i wyłączony z metryk semantycznych (14 prób; detekcja braków: 3 próby). '
             'JSON validity obejmuje 15 prób. Parameter accuracy jest odsetkiem prób z poprawnym całym zestawem parametrów. '
             'Detekcja pytań używa jawnych słów kluczowych; surowe pytania dostępne poniżej. '
             'Halucynacja obejmuje wymyślone lub błędne liczby oraz nieoczekiwane parametry. '
             'Tokens/s to szybkość dekodowania z timings, czas obejmuje pełny request HTTP. Wszystkie 15 prób bez historii rozmowy.', '',
             '| test | correct_actions | correct_order | correct_parameters | missing_detected | hallucinated_parameter | valid_json | validator_passed | time_s | tokens_s |',
             '|---|---|---|---|---|---|---|---|---|---|']
    keys=['correct_actions','correct_order','correct_parameters','missing_detected','hallucinated_parameter','valid_json','validator_passed']
    for r in data['tests']:
        flags=['—' if r.get(k) is None else ('tak' if r[k] else 'nie') for k in keys]
        lines.append('| '+str(r['test'])+' | '+' | '.join(flags)+f" | {r['time_s']:.2f} | {(r.get('tokens_s') or 0):.2f} |")
    lines += ['', '## Metryki', '']
    for key, value in metrics.items(): lines.append(f'- {key}: {value:.2%}' if 'accuracy' in key or 'rate' in key else f'- {key}: {value:.2f}')
    if data.get('before_metrics'):
        lines += ['', '## Before / after', '', '| Metryka | Before | After |', '|---|---|---|']
        for key in ('full_plan_success_rate', 'hallucination_rate', 'missing_parameter_detection_accuracy', 'json_validity_rate', 'mean_time_s', 'mean_tokens_s'):
            old, new = data['before_metrics'][key], metrics[key]
            fmt = (lambda value: f'{value:.2%}') if 'rate' in key or 'accuracy' in key else (lambda value: f'{value:.2f}')
            lines.append(f'| {key} | {fmt(old)} | {fmt(new)} |')
        lines += ['', 'Polecenia testowe identyczne. Before oceniał pomijanie niekompletnych akcji zgodnie ze starym promptem; after wymaga zachowania akcji z null. Full-plan success obejmuje prawidłowy INCOMPLETE, który pozostaje niewykonywalny.', '']
    lines += ['', '## Błędy zaobserwowane', '']
    for r in scored:
        if r.get('full_plan_success') is not True:
            lines.append(f"- Test {r['test']}: hallucinated_parameter={r.get('hallucinated_parameter')}; missing_detected={r.get('missing_detected')}; validator_passed={r.get('validator_passed')}.")
    lines += ['', '## Wykonanie i integralność', '', '```sh', 'python3 -m py_compile tests_x/benchmark_measurement_assistant_models.py', 'python3 tests_x/benchmark_measurement_assistant_models.py', '```', '', 'Komenda serwera:', '```sh', ' '.join(data['command']), '```', '', 'Ładowanie serwera: '+str(round(data.get('load_time_s',0),2))+' s.', 'Istniejące źródła bez zmian: '+str(data.get('existing_sources_unchanged', 'sprawdzanie po zakończeniu'))+'.', 'Utworzone pliki: tests_x/benchmark_measurement_assistant_models.py, benchmark_results/qwen35_2b_results.json, benchmark_results/qwen35_2b_report.md, benchmark_results/qwen35_2b_server.log.', '', '## Najczęstsze błędy i rekomendacje', '',
              '- Rozdzielić kontrakt planu niekompletnego od planu gotowego: dopuścić steps [] albo reprezentację brakujących parametrów. Obecnie poprawne pytanie nie mieści się w schema.',
              '- W definicjach i few-shot dodać polskie synonimy: płytka piezo, nastawnik polaryzacji; liczby słowne i numery łopatek.',
              '- Dodać przykłady wieloetapowe z zachowaniem nietypowej kolejności oraz przypadek liczby bez jednostki z pytaniem o jednostkę.',
              '- Każdą wymyśloną wartość oceniać niezależnie od walidatora; zgodność ze schema nie oznacza zgodności z poleceniem.',
              '- Nie przełączać modelu APP na podstawie pojedynczego zestawu; powtórzyć ocenę po uzgodnieniu kontraktu. Ten benchmark niczego w aplikacji nie zmienia.', '', '## Pełne odpowiedzi', '']
    for r in data['tests']:
        lines += [f"### Test {r['test']}: {r['request']}", '', '```text', r.get('raw_response') or r.get('error',''), '```', '',
                  'Walidator: '+json.dumps(r.get('validation'), ensure_ascii=False), '']
    path.write_text('\n'.join(lines),encoding='utf-8')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--binary', type=Path, default=Path.home()/'.local/share/app-v2/llama.cpp/build/bin/llama-server')
    ap.add_argument('--port', type=int, default=18766)
    ap.add_argument('--schema-format', choices=['nested','legacy'], default='nested')
    ap.add_argument('--output-dir', type=Path, default=ROOT/'benchmark_results')
    args=ap.parse_args()
    ns, cap=contract();prompt=ns['system_prompt']();schema=ns['response_schema']();validator=ns['PlanValidator']()
    before=source_hashes()
    # Refuse an occupied port, never attach to or terminate an application server.
    with socket.socket() as sock: sock.bind(('127.0.0.1',args.port))
    args.output_dir.mkdir(parents=True,exist_ok=True)
    cmd=[str(args.binary),'-hf','openresearchtools/Qwen3.5-2B-GGUF:Q4_K_M','--host','127.0.0.1','--port',str(args.port),
         '-c','2048','-t','4','-b','256','-ub','128','--cache-ram','0','-ngl','0','--parallel','1','--no-mmproj','--reasoning','off']
    data={'model':'Qwen3.5-2B Q4_K_M','command':cmd,'max_tokens':cap,'schema_format':args.schema_format,
          'source_hashes':before,'system_prompt':prompt,'response_schema':schema,
          'action_registry':[{'name':s.name,'description':s.description,'arguments':{k:a.schema() for k,a in s.arguments.items()}} for s in ns['ACTION_REGISTRY'].values()],
          'architecture_limitation':LIMITATION,'tests':[]}
    baseline = ROOT/'benchmark_results/before_null_contract/qwen35_2b_results.json'
    if baseline.is_file():
        data['before_metrics'] = json.loads(baseline.read_text())['metrics']
    jsonpath=args.output_dir/'qwen35_2b_results.json';mdpath=args.output_dir/'qwen35_2b_report.md'
    def save():
        if data['tests']:report(data,mdpath)
        jsonpath.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    base=f'http://127.0.0.1:{args.port}'
    log=(args.output_dir/'qwen35_2b_server.log').open('w');p=None
    try:
        start=time.monotonic();p=subprocess.Popen(cmd,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
        while True:
            if p.poll() is not None:raise RuntimeError(f'llama-server exited: {p.returncode}')
            try:
                if request(base+'/health',timeout=1).get('status')=='ok':break
            except (OSError,ValueError,RuntimeError):pass
            if time.monotonic()-start>120:raise TimeoutError('Server loading timeout')
            time.sleep(.2)
        data['load_time_s']=time.monotonic()-start
        print(f"Loaded in {data['load_time_s']:.2f}s",flush=True)
        for index,(user,expected) in enumerate(CASES,1):
            messages=[{'role':'system','content':prompt},{'role':'user','content':user}]
            payload={'messages':messages,'temperature':0.0,'max_tokens':cap,'response_format':{'type':'json_object'}}
            if args.schema_format=='nested':payload['response_format']['schema']=schema
            else:payload['json_schema']=schema
            row={'test':index,'request':user,'expected_intent':expected,'payload':payload,
                 'raw_response':None,'parsed_json':None,'valid_json':False,'validator_passed':False,
                 'completion_tokens':0,'tokens_s':None}
            started=time.monotonic()
            try:
                response=request(base+'/v1/chat/completions',payload,timeout=180)
                row['time_s']=time.monotonic()-started;row['http_response']=response
                row['completion_tokens']=response.get('usage',{}).get('completion_tokens',0)
                row['tokens_s']=response.get('timings',{}).get('predicted_per_second',row['completion_tokens']/row['time_s'])
                row['raw_response']=response['choices'][0]['message']['content']
                plan=ns['parse_response'](row['raw_response']);row['parsed_json']=plan;row['valid_json']=True
                val=validator.validate(plan,request=user)
                row['validation']={'errors':val.errors,'missing_parameters':val.missing_parameters,'runnable':val.runnable,'status':val.status}
                row['validator_passed']=not val.errors
                row.update(evaluate(plan,expected,val.missing_parameters))
                row['full_plan_success']=None if expected is None else all(row.get(k) is True for k in
                    ['valid_json','validator_passed','correct_actions','correct_order','correct_parameters'])
            except (OSError,ValueError,RuntimeError,KeyError,IndexError,TypeError) as exc:
                row['error']=str(exc);row['time_s']=time.monotonic()-started
                row.update(evaluate({},expected));row['full_plan_success']=False if expected is not None else None
            data['tests'].append(row);save()
            print(f"Test {index}: {row['time_s']:.2f}s; success={row['full_plan_success']}; hallucination={row.get('hallucinated_parameter')}",flush=True)
    finally:
        if p and p.poll() is None:
            p.terminate()
            try:p.wait(timeout=15)
            except subprocess.TimeoutExpired:p.kill();p.wait()
        log.close();data['existing_sources_unchanged']=before==source_hashes();save()
    print(json.dumps(data.get('metrics'),indent=2),flush=True)

if __name__=='__main__':main()
