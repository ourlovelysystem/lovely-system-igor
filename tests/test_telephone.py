import importlib.util, io, json, unittest
from pathlib import Path
from unittest.mock import Mock
p=Path(__file__).parents[1]/'src/telephone/app.py'; spec=importlib.util.spec_from_file_location('telephone',p); telephone=importlib.util.module_from_spec(spec); spec.loader.exec_module(telephone)
class TelephoneTests(unittest.TestCase):
 def setUp(self):
  self.table=Mock(); self.secret=Mock(); self.secret.get_secret_value.return_value={'SecretString':'{"allow_any_caller":true,"pin":"2468"}'}; self.lam=Mock()
 def reply(self, body): self.lam.invoke.return_value={'Payload':io.BytesIO(json.dumps({'body':json.dumps(body)}).encode())}
 def call(self, action=None, caller='+15550000001', event_type=None):
  e={'CallDetails':{'TransactionId':'c','Participants':([] if caller is None else [{'From':caller}])}}
  if action is not None: e['ActionData']={'Type':'ReceiveDigits','ReceivedDigits':action}
  if event_type: e['InvocationEventType']=event_type
  return e
 def lex_event(self,text='what is running'):
  return {'inputTranscript':text,'interpretations':[{'nluConfidence':{'score':.99}}],'sessionState':{'intent':{'name':'FallbackIntent'},'sessionAttributes':{'call_id':'c','conversation_id':'conv'}}}
 def assert_sma(self, out, actions=None):
  self.assertEqual('1.0',out['SchemaVersion']); self.assertIsInstance(out['Actions'],list)
  if actions is not None:self.assertEqual(actions,[x['Type'] for x in out['Actions']])
 def test_every_caller_identity_reaches_greeting_without_retention(self):
  for caller in (None, '', 'withheld', 'malformed caller id', '+442071838750'):
   with self.subTest(caller=caller):
    self.table.reset_mock(); out=telephone.chime(self.call(caller=caller),self.table,self.secret,self.lam,'conversation','arn:aws:lex:us-east-1:1:bot-alias/a/b','secret')
    self.assert_sma(out,['Speak','ReceiveDigits']); self.assertIn('PIN',out['Actions'][0]['Parameters']['Text'])
    if caller: self.assertNotIn(str(caller),str(self.table.mock_calls))
    self.assertNotIn('caller',str(self.table.mock_calls).lower())
 def test_complete_chime_pin_lex_igor_audible_sequence(self):
  greeting=telephone.chime(self.call(),self.table,self.secret,self.lam,'conversation','arn:aws:lex:us-east-1:1:bot-alias/a/b','secret')
  self.assert_sma(greeting,['Speak','ReceiveDigits']); self.assertEqual('^[0-9]{4}#$',greeting['Actions'][1]['Parameters']['InputDigitsRegex']); self.assertNotIn('TerminatorDigits',greeting['Actions'][1]['Parameters'])
  self.table.get_item.return_value={'Item':{'authentication':'PIN_REQUIRED','pin_attempts':0}}; self.reply({'conversation_id':'conv'})
  handoff=telephone.chime(self.call('2468#','+442071838750','ACTION_SUCCESSFUL'),self.table,self.secret,self.lam,'conversation','arn:aws:lex:us-east-1:1:bot-alias/a/b','secret')
  self.assert_sma(handoff,['StartBotConversation']); start=handoff['Actions'][0]; self.assertRegex(start['Parameters']['BotAliasArn'],r'^arn:aws:lex:[^:]+:\d+:bot-alias/[^/]+/[^/]+$'); self.assertEqual('en_US',start['Parameters']['LocaleId'])
  self.table.get_item.return_value={'Item':{'authentication':'AUTHENTICATED','conversation_id':'conv'}}; self.reply({'text':'Igor says the current job is healthy.'})
  heard=telephone.lex(self.lex_event(),self.table,self.lam,'conversation','control'); self.assertIn('Igor says',heard['messages'][0]['content']); self.assertEqual('ElicitIntent',heard['sessionState']['dialogAction']['type'])
  invoke=json_load(self.lam.invoke.call_args[1]['Payload']); self.assertIn('/conversations/conv/messages',invoke['rawPath']); persisted=str(self.table.mock_calls); self.assertNotIn('2468',persisted); self.assertNotIn('442071838750',persisted)
 def test_pin_attempt_limit_retries_then_hangs_up_without_pin_or_lex(self):
  for attempts, expected in ((0,['Speak','ReceiveDigits']),(1,['Speak','ReceiveDigits']),(2,['Speak','Hangup'])):
   with self.subTest(attempts=attempts):
    self.table.reset_mock(); self.lam.reset_mock(); self.table.get_item.return_value={'Item':{'authentication':'PIN_REQUIRED','pin_attempts':attempts}}
    out=telephone.chime(self.call('0000#',event_type='ACTION_SUCCESSFUL'),self.table,self.secret,self.lam,'conversation','arn:aws:lex:us-east-1:1:bot-alias/a/b','secret')
    self.assert_sma(out,expected); self.lam.invoke.assert_not_called(); self.assertNotIn('0000',str(self.table.mock_calls))
 def test_all_non_auth_chime_paths_return_contract_and_never_start_access(self):
  for event_type, action in [('ACTION_FAILED',{'Type':'ReceiveDigits'}),('HANGUP',{}),('ACTION_SUCCESSFUL',{'Type':'Speak'}),('UNKNOWN',{})]:
   with self.subTest(event_type=event_type):
    self.table.reset_mock(); self.lam.reset_mock(); e=self.call(event_type=event_type); e['ActionData']=action
    out=telephone.chime(e,self.table,self.secret,self.lam,'conversation','arn:aws:lex:us-east-1:1:bot-alias/a/b','secret')
    self.assert_sma(out,['Speak','Hangup']); self.lam.invoke.assert_not_called()
 def test_explicit_allow_any_caller_configuration_is_required(self):
  self.secret.get_secret_value.return_value={'SecretString':'{"pin":"2468"}'}
  out=telephone.chime(self.call(caller='withheld'),self.table,self.secret,self.lam,'conversation','alias','secret')
  self.assert_sma(out,['Speak','Hangup']); self.table.put_item.assert_not_called()
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
