import importlib.util, io, unittest
from pathlib import Path
from unittest.mock import Mock
p=Path(__file__).parents[1]/'src/telephone/app.py'; spec=importlib.util.spec_from_file_location('telephone',p); telephone=importlib.util.module_from_spec(spec); spec.loader.exec_module(telephone)
class TelephoneTests(unittest.TestCase):
 def setUp(self):
  self.table=Mock(); self.secret=Mock(); self.secret.get_secret_value.return_value={'SecretString':'{"allowlist":["+15550000001"],"pin":"2468"}'}; self.lam=Mock()
 def reply(self, body):
  import json
  self.lam.invoke.return_value={'Payload':io.BytesIO(json.dumps({'body':json.dumps(body)}).encode())}
 def call(self, action=None):
  e={'CallDetails':{'TransactionId':'c','Participants':[{'From':'+15550000001'}]}}
  if action is not None:e['ActionData']={'ReceivedDigits':action}
  return e
 def lex_event(self,text='what is running'):
  return {'inputTranscript':text,'interpretations':[{'nluConfidence':{'score':.99}}],'sessionState':{'intent':{'name':'FallbackIntent'},'sessionAttributes':{'call_id':'c','conversation_id':'conv'}}}
 def test_rejected_caller_never_stores_number(self):
  e={'CallDetails':{'TransactionId':'c','Participants':[{'From':'+15559999999'}]}}
  out=telephone.chime(e,self.table,self.secret,self.lam,'conversation','arn:aws:lex:us-east-1:1:bot-alias/a/b','secret')
  self.assertEqual('Hangup',out['Actions'][1]['Type']); self.table.put_item.assert_not_called(); self.assertNotIn('15559999999',str(out))
 def test_complete_chime_pin_lex_igor_audible_sequence(self):
  # inbound greeting and DTMF collection happen before Lex is ever started
  greeting=telephone.chime(self.call(),self.table,self.secret,self.lam,'conversation','arn:aws:lex:us-east-1:1:bot-alias/a/b','secret')
  self.assertEqual('1.0',greeting['SchemaVersion']); self.assertEqual(['Speak','ReceiveDigits'],[x['Type'] for x in greeting['Actions']])
  self.assertIn('PIN',greeting['Actions'][0]['Parameters']['Text']); self.assertEqual('^[0-9]{4}#$',greeting['Actions'][1]['Parameters']['InputDigitsRegex']); self.assertNotIn('TerminatorDigits',greeting['Actions'][1]['Parameters'])
  self.table.get_item.return_value={'Item':{'authentication':'PIN_REQUIRED'}}
  self.reply({'conversation_id':'conv'})
  handoff=telephone.chime(self.call('2468#'),self.table,self.secret,self.lam,'conversation','arn:aws:lex:us-east-1:1:bot-alias/a/b','secret')
  start=handoff['Actions'][0]; self.assertEqual('StartBotConversation',start['Type']); self.assertRegex(start['Parameters']['BotAliasArn'],r'^arn:aws:lex:[^:]+:\d+:bot-alias/[^/]+/[^/]+$')
  self.assertEqual('en_US',start['Parameters']['LocaleId']); self.assertEqual('c',start['Parameters']['SessionAttributes']['call_id'])
  self.table.get_item.return_value={'Item':{'authentication':'AUTHENTICATED','conversation_id':'conv'}}
  self.reply({'text':'Igor says the current job is healthy.'})
  heard=telephone.lex(self.lex_event(),self.table,self.lam,'conversation','control')
  self.assertIn('Igor says',heard['messages'][0]['content']); self.assertEqual('ElicitIntent',heard['sessionState']['dialogAction']['type'])
  invoke=json_load(self.lam.invoke.call_args[1]['Payload']); self.assertIn('/conversations/conv/messages',invoke['rawPath'])
  persisted=str(self.table.mock_calls); self.assertNotIn('2468',persisted); self.assertNotIn('15550000001',persisted)
 def test_lex_denies_unauthenticated_access(self):
  self.table.get_item.return_value={'Item':{'authentication':'PIN_REQUIRED'}}
  out=telephone.lex(self.lex_event(),self.table,self.lam,'conversation','control')
  self.assertIn('Authentication is required',out['messages'][0]['content']); self.lam.invoke.assert_not_called()
 def test_low_confidence_and_refusal_create_no_job(self):
  self.table.get_item.return_value={'Item':{'authentication':'AUTHENTICATED','conversation_id':'conv','pending_command':'delete x'}}
  out=telephone.lex({**self.lex_event('garble'),'interpretations':[{'nluConfidence':{'score':.2}}]},self.table,self.lam,'conversation','control')
  self.assertIn('repeat',out['messages'][0]['content']); self.lam.invoke.assert_not_called()
  out=telephone.lex(self.lex_event('no'),self.table,self.lam,'conversation','control'); self.assertIn('No job',out['messages'][0]['content']); self.lam.invoke.assert_not_called()
 def test_invalid_pin_does_not_start_lex_or_persist_pin(self):
  self.table.get_item.return_value={'Item':{'authentication':'PIN_REQUIRED'}}
  out=telephone.chime(self.call('0000#'),self.table,self.secret,self.lam,'conversation','arn:aws:lex:us-east-1:1:bot-alias/a/b','secret')
  self.assertEqual('1.0',out['SchemaVersion']); self.assertEqual(['Speak','Hangup'],[x['Type'] for x in out['Actions']]); self.lam.invoke.assert_not_called(); self.assertNotIn('0000',str(self.table.mock_calls))
 def test_confirmation_is_exactly_one_control_job(self):
  self.table.get_item.return_value={'Item':{'authentication':'AUTHENTICATED','conversation_id':'conv','pending_command':'create marker','confirmation':'PENDING'}}; self.reply({'job_id':'job'})
  out=telephone.lex(self.lex_event('confirm'),self.table,self.lam,'conversation','control')
  self.assertIn('one worker job',out['messages'][0]['content']); self.table.update_item.assert_called_once(); self.assertEqual(1,self.lam.invoke.call_count)
def json_load(payload):
 import json
 return json.loads(payload.decode())
