import contextlib
import importlib.util
import io
import json
import os
import re
import time
import unittest
import unittest.mock
from pathlib import Path
from unittest.mock import Mock

p=Path(__file__).parents[1]/'src/telephone/reference_pipeline.py'
spec=importlib.util.spec_from_file_location('rp',p)
rp=importlib.util.module_from_spec(spec)
spec.loader.exec_module(rp)

# Structural fixture transcribed from the official Amazon Chime SDK
# SpeakAndGetDigits action documentation.  It deliberately does not reuse
# production contract code, so obsolete parameter names cannot self-validate.
OFFICIAL_SPEAK_AND_GET_DIGITS_FIXTURE={
    'Type':'SpeakAndGetDigits',
    'Parameters':{
        'CallId':'leg',
        'SpeechParameters':{'Text':'Welcome to Igor. Enter your PIN followed by pound.','Engine':'neural','LanguageCode':'en-US','TextType':'text','VoiceId':'Joanna'},
        'FailureSpeechParameters':{'Text':'PIN entry timed out or was invalid. Please try again.','Engine':'neural','LanguageCode':'en-US','TextType':'text','VoiceId':'Joanna'},
        'InputDigitsRegex':'^[0-9]{1,32}$',
        'MinNumberOfDigits':1,
        'MaxNumberOfDigits':32,
        'TerminatorDigits':['#'],
        'InBetweenDigitsDurationInMilliseconds':5000,
        'Repeat':3,
        'RepeatDurationInMilliseconds':15000,
    },
}
AWS_REQUIRED_SPEAK_AND_GET_DIGITS_FIELDS={'CallId','SpeechParameters','RepeatDurationInMilliseconds'}
OBSOLETE_FIELDS={'TimeoutInSeconds','InBetweenDigitsTimeoutInMillis'}

def event(kind):
    return {'InvocationEventType':kind,'CallDetails':{'TransactionId':'fixture','Participants':[{'ParticipantTag':'LEG-A','CallId':'leg'}]}}
def payload(body):
    return {'Payload':Mock(read=lambda:json.dumps({'statusCode':202,'body':json.dumps(body)}).encode())}

class T(unittest.TestCase):
 def setUp(self):
  os.environ.update(TELEPHONE_AUTH_SECRET_NAME='secret',TELEPHONE_CALLS_TABLE='calls',CONVERSATION_FUNCTION_NAME='conversation',CONTROL_FUNCTION_NAME='control',REFERENCE_MEETING_TABLE='reference-meetings')
  self.table=Mock();self.sec=Mock();self.sec.get_secret_value.return_value={'SecretString':json.dumps({'allow_any_caller':True,'pin':'1234'})}
 def test_unauthenticated_and_failed_pin_have_no_meeting_or_tools(self):
  self.assertEqual('SpeakAndGetDigits',rp.handler(event('NEW_INBOUND_CALL'),None,Mock(),self.table,self.sec)['Actions'][0]['Type'])
  self.table.get_item.return_value={'Item':{'authentication':'PIN_REQUIRED','pin_attempts':0}};bad=event('ACTION_SUCCESSFUL');bad['ActionData']={'Type':'SpeakAndGetDigits','ReceivedDigits':'0000#'}
  self.assertEqual('SpeakAndGetDigits',rp.handler(bad,None,Mock(),self.table,self.sec)['Actions'][0]['Type'])
 def test_authenticated_pin_creates_bound_assertion_and_joins(self):
  self.table.get_item.return_value={'Item':{'authentication':'PIN_REQUIRED'}};m=Mock();m.create_meeting_with_attendees.return_value={'Meeting':{'MeetingId':'m'},'Attendees':[{'JoinToken':'j'}]};e=event('ACTION_SUCCESSFUL');e['ActionData']={'Type':'SpeakAndGetDigits','ReceivedDigits':'1234#'}
  reference=Mock();out=rp.handler(e,None,m,self.table,self.sec,reference);self.assertEqual(['Speak','JoinChimeMeeting'],[a['Type'] for a in out['Actions']]);self.assertEqual('PIN accepted. Connecting you to Igor.',out['Actions'][0]['Parameters']['Text']);row=self.table.put_item.call_args.kwargs['Item'];self.assertEqual('AUTHENTICATED',row['authentication']);self.assertTrue(rp._assertion(row['call_id'],row['conversation_id'],'1234'));reference.put_item.assert_called_once_with(Item={'meetingId':'m','transactionId':'fixture'})
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

class RuntimeContractTests(unittest.TestCase):
 def setUp(self): self.required={'TELEPHONE_AUTH_SECRET_NAME':'secret','TELEPHONE_CALLS_TABLE':'calls','CONTROL_FUNCTION_NAME':'control','CONVERSATION_FUNCTION_NAME':'conversation','REFERENCE_MEETING_TABLE':'reference-meetings'}
 def test_missing_runtime_configuration_returns_truthful_valid_sma_failure_before_clients(self):
  for absent in self.required:
   with self.subTest(absent=absent):
    env=dict(self.required);env.pop(absent)
    with unittest.mock.patch.dict(os.environ,env,clear=True): out=rp.handler(event('NEW_INBOUND_CALL'),None)
    self.assertEqual(['Speak','Hangup'],[a['Type'] for a in out['Actions']]);self.assertIn('configuration is unavailable',out['Actions'][0]['Parameters']['Text']);self.assertEqual('0',out['Actions'][1]['Parameters']['SipResponseCode'])
 def test_template_binds_all_handler_variables_and_only_intended_runtime_identities(self):
  template=(Path(__file__).parents[1]/'template.yaml').read_text();section=template.split('  ReferenceCompatibleVoiceFunction:',1)[1].split('  ReferenceCompatibleIgorBridgeFunction:',1)[0]
  for name,target in {'TELEPHONE_AUTH_SECRET_NAME':'!Ref TelephoneAuthSecretName','TELEPHONE_CALLS_TABLE':'!Ref TelephoneCallsTable','CONTROL_FUNCTION_NAME':'!Ref ControlFunction','CONVERSATION_FUNCTION_NAME':'!Ref ConversationFunction','REFERENCE_MEETING_TABLE':'!Ref ReferenceMeetingTableName'}.items(): self.assertIn(f'{name}: {target}',section)
  policy=template.split('  ReferenceCompatibleVoiceRole:',1)[1].split('  ReferenceCompatibleVoiceFunction:',1)[0];self.assertIn('Resource: !Ref TelephoneAuthSecretArn',policy);self.assertNotIn('TelephoneAuthSecretName}-*',policy);self.assertIn('Resource: [!GetAtt TelephoneCallsTable.Arn, !Sub "${TelephoneCallsTable.Arn}/index/MeetingIdIndex"]',policy);self.assertIn('Resource: [!GetAtt ConversationFunction.Arn, !GetAtt ControlFunction.Arn]',policy);self.assertIn('Action: dynamodb:PutItem',policy);self.assertIn('table/${ReferenceMeetingTableName}',policy)
 def test_new_inbound_pin_action_matches_official_fixture_and_rejects_obsolete_names(self):
  table=Mock();secret=Mock();secret.get_secret_value.return_value={'SecretString':json.dumps({'allow_any_caller':True,'pin':'1234'})}
  with unittest.mock.patch.dict(os.environ,self.required,clear=True): inbound=rp.handler(event('NEW_INBOUND_CALL'),None,Mock(),table,secret)
  action=inbound['Actions'][0]
  self.assertEqual(OFFICIAL_SPEAK_AND_GET_DIGITS_FIXTURE,action)
  self.assertTrue(AWS_REQUIRED_SPEAK_AND_GET_DIGITS_FIELDS <= set(action['Parameters']))
  self.assertFalse(OBSOLETE_FIELDS & set(action['Parameters']))
  for name in ('SpeechParameters','FailureSpeechParameters'): self.assertEqual({'Text','Engine','LanguageCode','TextType','VoiceId'},set(action['Parameters'][name]))
 def test_numeric_digits_followed_by_configured_terminator_satisfy_action_contract(self):
  parameters=OFFICIAL_SPEAK_AND_GET_DIGITS_FIXTURE['Parameters']
  self.assertEqual(['#'],parameters['TerminatorDigits'])
  self.assertIsNotNone(re.fullmatch(parameters['InputDigitsRegex'],'1234'))
  self.assertIsNone(re.fullmatch(parameters['InputDigitsRegex'],'1234#'))
 def test_chime_received_digits_without_terminator_authenticate_correct_pin(self):
  table=Mock();secret=Mock();secret.get_secret_value.return_value={'SecretString':json.dumps({'allow_any_caller':True,'pin':'1234'})}
  with unittest.mock.patch.dict(os.environ,self.required,clear=True):
   table.get_item.return_value={'Item':{'authentication':'PIN_REQUIRED'}};meetings=Mock();meetings.create_meeting_with_attendees.return_value={'Meeting':{'MeetingId':'meeting'},'Attendees':[{'JoinToken':'join'}]};pin=event('ACTION_SUCCESSFUL');pin['ActionData']={'Type':'SpeakAndGetDigits','ReceivedDigits':'1234'};reference=Mock();authenticated=rp.handler(pin,None,meetings,table,secret,reference)
  self.assertEqual(['Speak','JoinChimeMeeting'],[a['Type'] for a in authenticated['Actions']]);self.assertEqual('PIN accepted. Connecting you to Igor.',authenticated['Actions'][0]['Parameters']['Text']);self.assertEqual({'JoinToken':'join','CallId':'leg','MeetingId':'meeting'},authenticated['Actions'][1]['Parameters']);self.assertEqual({'MeetingId':'meeting','CallIdLegA':'leg','CallIdLegB':'','IgorConversationId':rp._opaque('fixture')},authenticated['TransactionAttributes']);row=table.put_item.call_args.kwargs['Item'];self.assertEqual('AUTHENTICATED',row['authentication']);self.assertTrue(row['authenticated_assertion']);reference.put_item.assert_called_once_with(Item={'meetingId':'meeting','transactionId':'fixture'})
 def test_safe_auth_diagnostic_logs_only_required_non_sensitive_fields(self):
  table=Mock();secret=Mock();secret.get_secret_value.return_value={'SecretString':json.dumps({'allow_any_caller':True,'pin':'1234'})};table.get_item.return_value={'Item':{'authentication':'PIN_REQUIRED','pin_attempts':0}}
  incoming=event('ACTION_SUCCESSFUL');incoming['Sequence']=7;incoming['ActionData']={'Type':'SpeakAndGetDigits','ReceivedDigits':'0000#','ErrorMessage':'must-not-log'};incoming['CallDetails']['TransactionId']='caller-identity-must-not-log'
  stream=io.StringIO()
  with contextlib.redirect_stdout(stream):
   with unittest.mock.patch.dict(os.environ,self.required,clear=True): rp.handler(incoming,None,Mock(),table,secret)
  lines=stream.getvalue().splitlines();logged=json.loads(lines[1])['chime_diagnostic']
  self.assertEqual({'auth_outcome':'REJECTED','call_correlation':rp._opaque('caller-identity-must-not-log'),'next_action':'SpeakAndGetDigits','invocation_event_type':'ACTION_SUCCESSFUL','invocation_sequence':7},logged)
  for sensitive in ('0000','1234','caller-identity-must-not-log','must-not-log','CallDetails','ReceivedDigits','ErrorMessage'): self.assertNotIn(sensitive,lines[1])
 def test_safe_lifecycle_diagnostic_is_preserved(self):
  incoming=event('ACTION_FAILED');incoming['Sequence']=7;incoming['ActionData']={'Type':'SpeakAndGetDigits','ErrorType':'InvalidDigits','ErrorMessage':'input failed','ReceivedDigits':'1234#'}
  stream=io.StringIO()
  with contextlib.redirect_stdout(stream):
   with unittest.mock.patch.dict(os.environ,{},clear=True): rp.handler(incoming,None)
  logged=json.loads(stream.getvalue())['chime_diagnostic']
  self.assertEqual({'InvocationEventType':'ACTION_FAILED','Sequence':7,'ActionType':'SpeakAndGetDigits','ErrorType':'InvalidDigits','ErrorMessage':'input failed'},logged)
  self.assertNotIn('1234',stream.getvalue());self.assertNotIn('CallDetails',stream.getvalue())
 def test_incorrect_pin_never_acknowledges_or_joins(self):
  table=Mock();secret=Mock();secret.get_secret_value.return_value={'SecretString':json.dumps({'allow_any_caller':True,'pin':'1234'})};table.get_item.return_value={'Item':{'authentication':'PIN_REQUIRED','pin_attempts':0}};pin=event('ACTION_SUCCESSFUL');pin['ActionData']={'Type':'SpeakAndGetDigits','ReceivedDigits':'0000#'}
  with unittest.mock.patch.dict(os.environ,self.required,clear=True): out=rp.handler(pin,None,Mock(),table,secret)
  self.assertNotIn('PIN accepted. Connecting you to Igor.',json.dumps(out));self.assertNotIn('JoinChimeMeeting',[a['Type'] for a in out['Actions']])
 def test_post_auth_handoff_contract(self):
  table=Mock();secret=Mock();secret.get_secret_value.return_value={'SecretString':json.dumps({'allow_any_caller':True,'pin':'1234'})}
  with unittest.mock.patch.dict(os.environ,self.required,clear=True):
   table.get_item.return_value={'Item':{'authentication':'PIN_REQUIRED'}};meetings=Mock();meetings.create_meeting_with_attendees.return_value={'Meeting':{'MeetingId':'meeting'},'Attendees':[{'JoinToken':'join'}]};pin=event('ACTION_SUCCESSFUL');pin['ActionData']={'Type':'SpeakAndGetDigits','ReceivedDigits':'1234#'};reference=Mock();authenticated=rp.handler(pin,None,meetings,table,secret,reference)
  self.assertEqual(['Speak','JoinChimeMeeting'],[a['Type'] for a in authenticated['Actions']]);self.assertEqual('PIN accepted. Connecting you to Igor.',authenticated['Actions'][0]['Parameters']['Text']);self.assertEqual({'JoinToken':'join','CallId':'leg','MeetingId':'meeting'},authenticated['Actions'][1]['Parameters']);self.assertEqual({'MeetingId':'meeting','CallIdLegA':'leg','CallIdLegB':'','IgorConversationId':rp._opaque('fixture')},authenticated['TransactionAttributes']);row=table.put_item.call_args.kwargs['Item'];self.assertEqual('AUTHENTICATED',row['authentication']);self.assertTrue(row['authenticated_assertion']);reference.put_item.assert_called_once_with(Item={'meetingId':'meeting','transactionId':'fixture'})
