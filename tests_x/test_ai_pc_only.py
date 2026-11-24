"""Transport/contract tests use mocked model output, not a language parser."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from modules.measurement_assistant.backend import LLMBackend
from modules.measurement_assistant.config import AssistantConfig
from modules.measurement_assistant.prompt_loader import load_messages, CONTEXT_DIR
from modules.measurement_assistant.plan_schema import PlanValidator
from tests_x.assistant_model_cases import CASES, expected

class PcOnlyTests(unittest.TestCase):
 def test_all_requests_forwarded_intact_and_model_result_preserved(self):
  for request, action, args in CASES:
   with self.subTest(request=request):
    output=expected(action,args)
    backend=LLMBackend()
    response={'choices':[{'message':{'content':json.dumps(output)}}]}
    with patch.object(backend,'ensure_ready'), patch.object(backend,'_request',return_value=response) as call:
     self.assertEqual(backend.generate(load_messages(request)),output)
     self.assertEqual(call.call_args.args[2]['messages'][-1]['content'],request)
    checked=PlanValidator().validate(output,request)
    self.assertFalse(checked.errors)
    self.assertEqual(checked.runnable,action not in {'answer','error'})

 def test_loader_order_sources_and_unsupported_files(self):
  import shutil
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)
   for name in ('assistant_prompt.txt','station_and_actions.json','output_schema.json'):
    shutil.copy(CONTEXT_DIR/name,root/name)
   (root/'data').mkdir()
   for name,content in [('b.txt','SECOND'),('a.md','FIRST'),('x.pdf','IGNORED'),('README.md','PLACEHOLDER')]:
    (root/'data'/name).write_text(content)
   text=load_messages('hello',root)[0]['content']
   self.assertLess(text.index('SOURCE: a.md'),text.index('SOURCE: b.txt'))
   self.assertIn('FIRST',text)
   self.assertNotIn('IGNORED',text)
   self.assertNotIn('PLACEHOLDER',text)

 def test_debug_and_truncation(self):
  with tempfile.TemporaryDirectory() as tmp:
   backend=LLMBackend(AssistantConfig(debug_io=True,runs_dir=Path(tmp)))
   raw=json.dumps(expected('answer',{}))
   response={'choices':[{'message':{'content':raw},'finish_reason':'length'}]}
   with patch.object(backend,'ensure_ready'), patch.object(backend,'_request',return_value=response):
    with self.assertRaises(ValueError): backend.generate('pytanie')
   self.assertEqual((Path(tmp)/'last_model_response.json').read_text(),raw)
   self.assertEqual(json.loads((Path(tmp)/'last_model_input.txt').read_text())[-1]['content'],'pytanie')

 def test_defaults_and_no_semantic_override(self):
  self.assertFalse(AssistantConfig().execution_enabled)
  self.assertFalse(AssistantConfig().debug_io)
  # Structural validation cannot prove whether the model invented a supplied value.
  self.assertTrue(PlanValidator().validate(expected('set_temperature',{'value_c':30}),'dowolna parafraza').runnable)

 def test_paraphrases_not_in_context(self):
  context=load_messages('test')[0]['content']
  for request,_,_ in CASES[11:]: self.assertNotIn(request,context)
