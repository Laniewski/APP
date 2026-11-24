"""Explicit real-model semantic acceptance run. No Qt, drivers or runner imports."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from modules.measurement_assistant.backend import LLMBackend
from modules.measurement_assistant.config import AssistantConfig
from modules.measurement_assistant.plan_schema import PlanValidator
from tests_x.assistant_model_cases import CASES, matches
from dataclasses import replace


def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--limit',type=int,default=len(CASES),help='Run only the first N cases for diagnosis.')
 options=parser.parse_args()
 if not 1 <= options.limit <= len(CASES): parser.error('limit outside case count')
 backend=LLMBackend(replace(AssistantConfig.from_env(),execution_enabled=False,timeout_s=600,debug_io=True))
 results=[]
 try:
  for request,action,args in CASES[:options.limit]:
   try:
    output=backend.generate(request,status=lambda s:print(s,flush=True))
    valid=not PlanValidator().validate(output).errors
    row=dict(request=request,result=output,passed=valid and matches(output,action,args),metrics=backend.last_metrics)
   except Exception as exc: row=dict(request=request,passed=False,error=str(exc))
   results.append(row)
   print(json.dumps(row,ensure_ascii=False),flush=True)
   backend.config.runs_dir.mkdir(parents=True,exist_ok=True)
   (backend.config.runs_dir/'model_acceptance.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
 finally: backend.shutdown()
 return 0 if all(row['passed'] for row in results) else 1

if __name__=='__main__':sys.exit(main())
