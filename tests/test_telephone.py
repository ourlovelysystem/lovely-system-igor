import ast, importlib.util, io, json, sys, unittest
from pathlib import Path
from unittest.mock import Mock, patch

p=Path(__file__).parents[1]/'src/telephone/app.py'
spec=importlib.util.spec_from_file_location('telephone',p)
telephone=importlib.util.module_from_spec(spec); spec.loader.exec_module(telephone)

class TelephoneTests(unittest.TestCase):
 def event(self,event_type='NEW_INBOUND_CALL',action_type=None):
  e={'SchemaVersion':'1.0','Sequence':7,'InvocationEventType':event_type,'CallDetails':{'TransactionId':'redacted','Participants':[{'ParticipantTag':'LEG-A','CallId':'must-never-echo'}]}}
  if action_type: e['ActionData']={'Type':action_type,'Parameters':{'CallId':'must-never-echo'}}
  return e
 def assert_contract(self,out):
  self.assertEqual('1.0',out['SchemaVersion']); self.assertIsInstance(out['Actions'],list)
  for action in out['Actions']: telephone._validate_action(action)
 def test_new_inbound_call_is_exactly_the_minimal_playaudio_response(self):
  with patch.dict('os.environ', {'DIAGNOSTIC_AUDIO_BUCKET':'diagnostic-bucket'}): out=telephone.chime(self.event(),Mock(),Mock(),Mock(),'conversation','lex','secret')
  expected={'SchemaVersion':'1.0','Actions':[{'Type':'PlayAudio','Parameters':{'ParticipantTag':'LEG-A','AudioSource':{'Type':'S3','BucketName':'diagnostic-bucket','Key':'igor-018/diagnostic.wav'}}}]}
  self.assertEqual(expected,out); self.assert_contract(out)
  encoded=json.dumps(out)
  for forbidden in ('CallId','Hangup','Repeat','PlaybackTerminators','Lex','DynamoDB','Secrets','conversation','authentication'): self.assertNotIn(forbidden,encoded)
 def test_handler_new_inbound_constructs_no_aws_clients_or_dependencies(self):
  with patch.dict(sys.modules, {'boto3':object()}), patch.dict('os.environ', {'DIAGNOSTIC_AUDIO_BUCKET':'diagnostic-bucket'}): out=telephone.handler(self.event(),None)
  self.assertEqual(['PlayAudio'],[a['Type'] for a in out['Actions']]); self.assert_contract(out)
 def test_action_successful_only_returns_supported_zero_hangup(self):
  out=telephone.chime(self.event('ACTION_SUCCESSFUL','PlayAudio'))
  self.assertEqual({'SchemaVersion':'1.0','Actions':[{'Type':'Hangup','Parameters':{'ParticipantTag':'LEG-A','SipResponseCode':'0'}}]},out)
  self.assert_contract(out)
 def test_failure_and_terminal_paths_use_supported_hangup_without_dependencies(self):
  for event_type in ('ACTION_FAILED','INVALID_LAMBDA_RESPONSE','HANGUP','UNKNOWN'):
   with self.subTest(event_type=event_type):
    out=telephone.chime(self.event(event_type,'PlayAudio'))
    self.assertEqual(['Hangup'],[a['Type'] for a in out['Actions']]); self.assertEqual({'ParticipantTag':'LEG-A','SipResponseCode':'480'},out['Actions'][0]['Parameters']); self.assert_contract(out)
 def test_hangup_rejects_any_code_not_documented_by_igor018_contract(self):
  for code in ('0','480','486'): telephone._validate_action({'Type':'Hangup','Parameters':{'ParticipantTag':'LEG-A','SipResponseCode':code}})
  with self.assertRaises(ValueError): telephone._validate_action({'Type':'Hangup','Parameters':{'ParticipantTag':'LEG-A','SipResponseCode':'200'}})
 def test_safe_log_has_only_approved_fields_and_no_event_payload(self):
  event=self.event(); event['ErrorType']='MediaFailure'; event['ErrorMessage']='safe diagnostic'; event['sensitive']='do-not-log'
  with patch.dict('os.environ', {'DIAGNOSTIC_AUDIO_BUCKET':'diagnostic-bucket'}), patch('builtins.print') as printed: telephone.handler(event,None)
  payload=json.loads(printed.call_args.args[0])['chime_diagnostic']
  self.assertEqual({'event_type','sequence','action_type','ErrorType','ErrorMessage'},set(payload)); self.assertNotIn('must-never-echo',printed.call_args.args[0]); self.assertNotIn('sensitive',printed.call_args.args[0])
 def test_diagnostic_source_has_no_legacy_dependencies_on_chime_route(self):
  tree=ast.parse(p.read_text())
  handler=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='handler')
  source=ast.get_source_segment(p.read_text(),handler)
  self.assertNotIn('boto3',source.split('if "CallDetails" in event:')[1].split('import boto3')[0])

if __name__=='__main__': unittest.main()
