"""Regression: historical grounding cannot authorize the new runner."""
import unittest
from modules.measurement_assistant.grounding import grounded_plan
from modules.measurement_assistant.plan_schema import PlanValidator, parse_response
from modules.measurement_assistant.script_builder import ScriptBuilder
from tests_x.assistant_model_cases import expected

class StructuralValidationTests(unittest.TestCase):
 def test_old_plans_are_not_executable(self):
  plan=grounded_plan('Poczekaj 5 sekund')
  self.assertFalse(PlanValidator().validate(plan).runnable)
  with self.assertRaises(ValueError): ScriptBuilder().build(plan)

 def test_bad_values_unknown_args_and_unavailable_adapters(self):
  cases=[('set_temperature',{}),('set_temperature',{'value_c':None}),('set_temperature',{'value_c':True}),('set_temperature',{'value_c':201}),('set_polarization_angle',{'paddle':3,'angle_deg':40}),('set_polarization_angle',{'paddle':[],'angle_deg':40}),('wait',{'seconds':float('nan')}),('wait',{'seconds':1,'code':'evil'}),('auto_polarization',{}),('start_ramp',{'target_voltage':30,'ramp_rate_v_per_s':5}),('unknown',{})]
  for action,args in cases:
   with self.subTest(action=action,args=args):
    result=PlanValidator().validate(expected(action,args))
    self.assertTrue(result.errors)
    self.assertFalse(result.runnable)

 def test_nonprocedures_cannot_generate_scripts(self):
  for kind in ['answer','error']:
   value=expected(kind,{})
   self.assertFalse(PlanValidator().validate(value).runnable)
   with self.assertRaises(ValueError): ScriptBuilder().build(value)
   value['steps']=[{'action':'heater_on','args':{}}]
   self.assertTrue(PlanValidator().validate(value).errors)

 def test_strict_json(self):
  for raw in ['{"type":"answer","type":"procedure"}', '{"v":NaN}', '[]', '```json\n{}\n```']:
   with self.assertRaises(ValueError): parse_response(raw)

 def test_catalog_and_output_schema_have_identical_argument_contracts(self):
  from modules.measurement_assistant.action_registry import action_definitions
  from modules.measurement_assistant.plan_schema import response_schema
  variants=response_schema()['oneOf'][2]['properties']['steps']['items']['oneOf']
  by_name={item['properties']['action']['const']:item['properties']['args'] for item in variants}
  definitions=action_definitions()
  self.assertEqual(set(by_name),set(definitions))
  for name, action in definitions.items():
   contract=by_name[name]
   self.assertFalse(contract['additionalProperties'])
   self.assertEqual(set(contract['properties']),set(action['arguments']))
   self.assertEqual(set(contract['required']),{k for k,a in action['arguments'].items() if a['required']})
   for key,arg in action['arguments'].items():
    expected={k:arg[k] for k in ('type','minimum','maximum') if k in arg}
    if 'choices' in arg: expected['enum']=arg['choices']
    self.assertEqual(contract['properties'][key],expected)

 def test_editing_catalog_cannot_authorize_unknown_adapter(self):
  from unittest.mock import patch
  from modules.measurement_assistant.action_registry import action_definitions
  definitions=action_definitions()
  definitions['auto_polarization']['executable']=True
  with patch('modules.measurement_assistant.plan_schema.action_definitions',return_value=definitions):
   self.assertFalse(PlanValidator().validate(expected('auto_polarization',{})).runnable)
