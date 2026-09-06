import importlib.util, io, unittest
from pathlib import Path
from unittest.mock import Mock
p=Path(__file__).parents[1]/'src/telephone/app.py'; spec=importlib.util.spec_from_file_location('telephone',p); telephone=importlib.util.module_from_spec(spec); spec.loader.exec_module(telephone)
class TelephoneTests(unittest.TestCase):
 def setUp(self): self.table=Mock(); self.secret=Mock(); self.secret.get_secret_value.return_value={'SecretString':'{"allowlist":["+15550000001"],"pin":"2468"}'}; self.lam=Mock()
 def test_rejected_caller_never_stores_number(self):
  out=telephone.chime({'CallDetails':{'TransactionId':'c','Participants':[{'From':'+15559999999'}]}},self.table,self.secret,'bot','secret')
  self.assertEqual('Hangup',out['Actions'][1]['Type']); self.table.put_item.assert_not_called(); self.assertNotIn('15559999999',str(out))
 def test_pin_not_persisted_and_creates_shared_conversation(self):
  self.table.get_item.return_value={'Item':{'authentication':'PIN_REQUIRED'}}
  self.lam.invoke.return_value={'Payload':io.BytesIO(b'{"body":"{\\"conversation_id\\":\\"conv\\"}"}')}
  out=telephone.lex({'inputTranscript':'2468','sessionState':{'sessionAttributes':{'call_id':'c'}}},self.table,self.secret,self.lam,'conversation','control','secret')
  self.assertIn('Authenticated',out['messages'][0]['content']); self.assertNotIn('2468',str(self.table.mock_calls))
 def test_confirmation_is_exactly_one_control_job(self):
  self.table.get_item.return_value={'Item':{'authentication':'AUTHENTICATED','conversation_id':'conv','pending_command':'create harmless marker','confirmation':'PENDING'}}
  self.lam.invoke.return_value={'Payload':io.BytesIO(b'{"body":"{\\"job_id\\":\\"job\\"}"}')}
  out=telephone.lex({'inputTranscript':'confirm','sessionState':{'sessionAttributes':{'call_id':'c'}}},self.table,self.secret,self.lam,'conversation','control','secret')
  self.assertIn('one worker job',out['messages'][0]['content']); self.table.update_item.assert_called_once(); self.assertEqual(1,self.lam.invoke.call_count)
 def test_low_confidence_and_refusal_create_no_job(self):
  self.table.get_item.return_value={'Item':{'authentication':'AUTHENTICATED','conversation_id':'conv','pending_command':'delete x'}}
  out=telephone.lex({'inputTranscript':'garble','interpretations':[{'nluConfidence':{'score':.2}}],'sessionState':{'sessionAttributes':{'call_id':'c'}}},self.table,self.secret,self.lam,'conversation','control','secret')
  self.assertIn('repeat',out['messages'][0]['content']); self.lam.invoke.assert_not_called()
  out=telephone.lex({'inputTranscript':'no','sessionState':{'sessionAttributes':{'call_id':'c'}}},self.table,self.secret,self.lam,'conversation','control','secret')
  self.assertIn('No job',out['messages'][0]['content']); self.lam.invoke.assert_not_called()
