import importlib.util,json,os,time,unittest
from pathlib import Path
from unittest.mock import Mock
p=Path(__file__).parents[1]/'src/telephone/reference_pipeline.py';spec=importlib.util.spec_from_file_location('rp',p);rp=importlib.util.module_from_spec(spec);spec.loader.exec_module(rp)
def event(kind):return {'InvocationEventType':kind,'CallDetails':{'TransactionId':'fixture','Participants':[{'ParticipantTag':'LEG-A','CallId':'leg'}]}}
def payload(body):return {'Payload':Mock(read=lambda:json.dumps({'statusCode':202,'body':json.dumps(body)}).encode())}
class T(unittest.TestCase):
 def setUp(self):os.environ.update(TELEPHONE_AUTH_SECRET_NAME='secret',CONVERSATION_FUNCTION_NAME='conversation',CONTROL_FUNCTION_NAME='control');self.table=Mock();self.sec=Mock();self.sec.get_secret_value.return_value={'SecretString':json.dumps({'allow_any_caller':True,'pin':'1234'})}
 def test_unauthenticated_and_failed_pin_have_no_meeting_or_tools(self):
  self.assertEqual('SpeakAndGetDigits',rp.handler(event('NEW_INBOUND_CALL'),None,Mock(),self.table,self.sec)['Actions'][0]['Type'])
  self.table.get_item.return_value={'Item':{'authentication':'PIN_REQUIRED','pin_attempts':0}};bad=event('ACTION_SUCCESSFUL');bad['ActionData']={'Type':'SpeakAndGetDigits','ReceivedDigits':'0000#'}
  self.assertEqual('SpeakAndGetDigits',rp.handler(bad,None,Mock(),self.table,self.sec)['Actions'][0]['Type'])
 def test_authenticated_pin_creates_bound_assertion_and_joins(self):
  self.table.get_item.return_value={'Item':{'authentication':'PIN_REQUIRED'}};m=Mock();m.create_meeting_with_attendees.return_value={'Meeting':{'MeetingId':'m'},'Attendees':[{'JoinToken':'j'}]};e=event('ACTION_SUCCESSFUL');e['ActionData']={'Type':'SpeakAndGetDigits','ReceivedDigits':'1234#'}
  self.assertEqual('JoinChimeMeeting',rp.handler(e,None,m,self.table,self.sec)['Actions'][0]['Type']);row=self.table.put_item.call_args.kwargs['Item'];self.assertEqual('AUTHENTICATED',row['authentication']);self.assertTrue(rp._assertion(row['call_id'],row['conversation_id'],'1234'))
 def call(self,text,row=None):
  row=row or {'call_id':'c'*32,'conversation_id':'v','authentication':'AUTHENTICATED','assertion_expires_at':int(time.time()+100),'authenticated_assertion':rp._assertion('c'*32,'v','1234')};self.table.query.return_value={'Items':[row]};return rp.bridge({'meeting_id':'m','transcript':text},None,Mock(),self.table)
 def test_authenticated_conversation_passes_assertion_to_tools_boundary(self):
  lam=Mock();lam.invoke.return_value={'Payload':Mock(read=lambda:json.dumps({'statusCode':200,'body':json.dumps({'text':'answer'})}).encode())};row={'call_id':'c'*32,'conversation_id':'v','authentication':'AUTHENTICATED','assertion_expires_at':int(time.time()+100),'authenticated_assertion':rp._assertion('c'*32,'v','1234')};self.table.query.return_value={'Items':[row]};self.assertEqual('answer',rp.bridge({'meeting_id':'m','transcript':'question'},None,lam,self.table)['response']);self.assertIn('telephone_assertion',json.loads(lam.invoke.call_args.kwargs['Payload'])['body'])
 def test_action_awaits_confirmation_and_submits_exactly_once(self):
  row={'call_id':'c'*32,'conversation_id':'v','authentication':'AUTHENTICATED','assertion_expires_at':int(time.time()+100),'authenticated_assertion':'x'};self.assertIn('Confirmation is required',self.call('deploy harmless inspection',row)['response']);row.update(confirmation='PENDING',pending_action='deploy harmless inspection',pending_expires_at=int(time.time()+100));lam=Mock();lam.invoke.return_value=payload({'job_id':'job1'});self.table.query.return_value={'Items':[row]};self.assertIn('job1',rp.bridge({'meeting_id':'m','transcript':'confirm'},None,lam,self.table)['response']);self.assertEqual(1,lam.invoke.call_count)
 def test_expired_mismatched_and_duplicate_confirmation_do_not_submit(self):
  row={'call_id':'c'*32,'conversation_id':'v','authentication':'AUTHENTICATED','assertion_expires_at':int(time.time()+100),'confirmation':'PENDING','pending_action':'x','pending_expires_at':0};self.assertIn('no current',self.call('confirm',row)['response']);row['pending_expires_at']=int(time.time()+100);self.table.update_item.side_effect=Exception('conditional');self.assertIn('already processed',self.call('confirm',row)['response'])
 def test_executor_error_is_truthful(self):
  row={'call_id':'c'*32,'conversation_id':'v','authentication':'AUTHENTICATED','assertion_expires_at':int(time.time()+100),'confirmation':'PENDING','pending_action':'x','pending_expires_at':int(time.time()+100)};lam=Mock();lam.invoke.return_value={'FunctionError':'Unhandled'};self.table.query.return_value={'Items':[row]};self.assertIn('Execution failed',rp.bridge({'meeting_id':'m','transcript':'confirm'},None,lam,self.table)['response'])
