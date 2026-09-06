import importlib.util, io, json, unittest
from pathlib import Path
from unittest.mock import Mock
p=Path(__file__).parents[1]/'src/telephone/app.py'; spec=importlib.util.spec_from_file_location('telephone',p); telephone=importlib.util.module_from_spec(spec); spec.loader.exec_module(telephone)
class TelephoneTests(unittest.TestCase):
 def setUp(self):
  self.table=Mock(); self.secret=Mock(); self.secret.get_secret_value.return_value={'SecretString':'{"allow_any_caller":true,"pin":"2468"}'}; self.lam=Mock()
 def reply(self, body): self.lam.invoke.return_value={'Payload':io.BytesIO(json.dumps({'body':json.dumps(body)}).encode())}
 def call(self, action=None, event_type=None):
  # Structural fixture based on the documented Amazon Chime SDK PSTN Audio
  # inbound event: LEG-A supplies the CallId used by audio actions.
  e={'SchemaVersion':'1.0','Sequence':1,'CallDetails':{'TransactionId':'c','Participants':[{'CallId':'leg-a-call-id','ParticipantTag':'LEG-A','Direction':'Inbound'}]}}
  if action is not None: e['ActionData']={'Type':'SpeakAndGetDigits','ReceivedDigits':action,'Parameters':{'CallId':'leg-a-call-id'}}
  if event_type: e['InvocationEventType']=event_type
  return e
 def lex_event(self,text='what is running'):
  return {'inputTranscript':text,'interpretations':[{'nluConfidence':{'score':.99}}],'sessionState':{'intent':{'name':'FallbackIntent'},'sessionAttributes':{'call_id':'c','conversation_id':'conv'}}}
 def assert_sma(self, out, actions=None):
  self.assertEqual('1.0',out['SchemaVersion']); self.assertIsInstance(out['Actions'],list)
  if actions is not None:self.assertEqual(actions,[x['Type'] for x in out['Actions']])
 def assert_contract(self, out):
  self.assert_sma(out)
  for action in out['Actions']: telephone._validate_action(action)
 def test_inbound_fixture_returns_documented_speak_and_get_digits(self):
  out=telephone.chime(self.call(),self.table,self.secret,self.lam,'conversation','arn:aws:lex:us-east-1:1:bot-alias/a/b','secret')
  self.assert_sma(out,['SpeakAndGetDigits']); self.assert_contract(out)
  p=out['Actions'][0]['Parameters']; self.assertEqual('leg-a-call-id',p['CallId']); self.assertEqual({'Text':'Welcome to Igor. Enter your PIN followed by pound.'},p['SpeechParameters'])
  self.assertEqual('^[0-9]{1,32}#$',p['InputDigitsRegex']); self.assertEqual(['#'],p['TerminatorDigits'])
  self.assertNotIn('2468',str(out)); self.assertNotIn('caller',str(self.table.mock_calls).lower())
 def test_complete_chime_pin_lex_igor_audible_sequence(self):
  greeting=telephone.chime(self.call(),self.table,self.secret,self.lam,'conversation','arn:aws:lex:us-east-1:1:bot-alias/a/b','secret')
  self.assert_sma(greeting,['SpeakAndGetDigits']); self.assert_contract(greeting)
  self.table.get_item.return_value={'Item':{'authentication':'PIN_REQUIRED','pin_attempts':0}}; self.reply({'conversation_id':'conv'})
  handoff=telephone.chime(self.call('2468#','ACTION_SUCCESSFUL'),self.table,self.secret,self.lam,'conversation','arn:aws:lex:us-east-1:1:bot-alias/a/b','secret')
  self.assert_sma(handoff,['StartBotConversation']); self.assert_contract(handoff)
  self.table.get_item.return_value={'Item':{'authentication':'AUTHENTICATED','conversation_id':'conv'}}; self.reply({'text':'Igor says the current job is healthy.'})
  heard=telephone.lex(self.lex_event(),self.table,self.lam,'conversation','control'); self.assertIn('Igor says',heard['messages'][0]['content']); self.assertEqual('ElicitIntent',heard['sessionState']['dialogAction']['type'])
  invoke=json_load(self.lam.invoke.call_args[1]['Payload']); self.assertIn('/conversations/conv/messages',invoke['rawPath']); self.assertNotIn('2468',str(self.table.mock_calls))
 def test_pin_attempt_limit_retries_then_hangs_up_without_pin_or_lex(self):
  for attempts, expected in ((0,['SpeakAndGetDigits']),(1,['SpeakAndGetDigits']),(2,['Speak','Hangup'])):
   with self.subTest(attempts=attempts):
    self.table.reset_mock(); self.lam.reset_mock(); self.table.get_item.return_value={'Item':{'authentication':'PIN_REQUIRED','pin_attempts':attempts}}
    out=telephone.chime(self.call('0000#','ACTION_SUCCESSFUL'),self.table,self.secret,self.lam,'conversation','arn:aws:lex:us-east-1:1:bot-alias/a/b','secret')
    self.assert_sma(out,expected); self.assert_contract(out); self.lam.invoke.assert_not_called(); self.assertNotIn('0000',str(self.table.mock_calls))
 def test_every_chime_lifecycle_event_has_a_valid_contract_response(self):
  for event_type, action in [('ACTION_FAILED',{'Type':'SpeakAndGetDigits','Parameters':{'CallId':'leg-a-call-id'}}),('INVALID_LAMBDA_RESPONSE',{'Type':'SpeakAndGetDigits','Parameters':{'CallId':'leg-a-call-id'}}),('HANGUP',{'Type':'Hangup','Parameters':{'CallId':'leg-a-call-id'}}),('ACTION_SUCCESSFUL',{'Type':'Speak','Parameters':{'CallId':'leg-a-call-id'}}),('UNKNOWN',{})]:
   with self.subTest(event_type=event_type):
    self.table.reset_mock(); self.lam.reset_mock(); e=self.call(event_type=event_type); e['ActionData']=action
    out=telephone.chime(e,self.table,self.secret,self.lam,'conversation','arn:aws:lex:us-east-1:1:bot-alias/a/b','secret')
    self.assert_sma(out,['Speak','Hangup']); self.assert_contract(out); self.lam.invoke.assert_not_called()
 def test_explicit_allow_any_caller_configuration_is_required(self):
  self.secret.get_secret_value.return_value={'SecretString':'{"pin":"2468"}'}
  out=telephone.chime(self.call(),self.table,self.secret,self.lam,'conversation','alias','secret')
  self.assert_sma(out,['Speak','Hangup']); self.assert_contract(out); self.table.put_item.assert_not_called()
 def test_lex_denies_unauthenticated_access(self):
  self.table.get_item.return_value={'Item':{'authentication':'PIN_REQUIRED'}}; out=telephone.lex(self.lex_event(),self.table,self.lam,'conversation','control'); self.assertIn('Authentication is required',out['messages'][0]['content']); self.lam.invoke.assert_not_called()
 def test_low_confidence_and_refusal_create_no_job(self):
  self.table.get_item.return_value={'Item':{'authentication':'AUTHENTICATED','conversation_id':'conv','pending_command':'delete x'}}
  out=telephone.lex({**self.lex_event('garble'),'interpretations':[{'nluConfidence':{'score':.2}}]},self.table,self.lam,'conversation','control'); self.assertIn('repeat',out['messages'][0]['content']); self.lam.invoke.assert_not_called()
  out=telephone.lex(self.lex_event('no'),self.table,self.lam,'conversation','control'); self.assertIn('No job',out['messages'][0]['content']); self.lam.invoke.assert_not_called()
 def test_confirmation_is_exactly_one_control_job(self):
  self.table.get_item.return_value={'Item':{'authentication':'AUTHENTICATED','conversation_id':'conv','pending_command':'create marker','confirmation':'PENDING'}}; self.reply({'job_id':'job'})
  out=telephone.lex(self.lex_event('confirm'),self.table,self.lam,'conversation','control'); self.assertIn('one worker job',out['messages'][0]['content']); self.table.update_item.assert_called_once(); self.assertEqual(1,self.lam.invoke.call_count)
def json_load(payload): return json.loads(payload.decode())
