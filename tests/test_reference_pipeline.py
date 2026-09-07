"""Fixtures structurally derived from the pinned source archive's SMA transitions.
No fixture invents a direct Igor action contract."""
import importlib.util, json, os, unittest
from pathlib import Path
from unittest.mock import Mock
p=Path(__file__).parents[1]/'src/telephone/reference_pipeline.py'; spec=importlib.util.spec_from_file_location('rp',p); rp=importlib.util.module_from_spec(spec); spec.loader.exec_module(rp)
def event(kind,attrs=None):
 return {'SchemaVersion':'1.0','InvocationEventType':kind,'CallDetails':{'TransactionId':'fixture-transaction','TransactionAttributes':attrs or {},'Participants':[{'ParticipantTag':'LEG-A','CallId':'leg-a-fixture'},{'ParticipantTag':'LEG-B','CallId':'leg-b-fixture'}]}}
class ReferencePipelineTests(unittest.TestCase):
 def test_source_structured_inbound_join_fixture_and_durable_opaque_link(self):
  meetings=Mock(); meetings.create_meeting_with_attendees.return_value={'Meeting':{'MeetingId':'meeting-fixture'},'Attendees':[{'JoinToken':'join-token-fixture'}]}; table=Mock()
  actual=rp.handler(event('NEW_INBOUND_CALL'),None,meetings,table)
  self.assertEqual(actual['SchemaVersion'],'1.0'); self.assertEqual(actual['Actions'],[{'Type':'JoinChimeMeeting','Parameters':{'JoinToken':'join-token-fixture','CallId':'leg-a-fixture','MeetingId':'meeting-fixture'}}])
  self.assertEqual(actual['TransactionAttributes']['MeetingId'],'meeting-fixture'); self.assertEqual(actual['TransactionAttributes']['CallIdLegA'],'leg-a-fixture')
  stored=table.put_item.call_args.kwargs['Item']; self.assertEqual(stored['record_key'],'CALL'); self.assertNotIn('fixture-transaction',json.dumps(stored)); self.assertNotIn('leg-a-fixture',json.dumps(stored)); self.assertEqual(stored['media_state'],'JOIN_REQUESTED')
 def test_source_structured_join_response_and_hangup_fixtures(self):
  attrs={'MeetingId':'meeting-fixture','CallIdLegA':'leg-a-fixture','CallIdLegB':'leg-b-fixture','IgorConversationId':'conversation-fixture'}; meetings=Mock()
  joined=event('ACTION_SUCCESSFUL',attrs); joined['ActionData']={'Type':'JoinChimeMeeting'}
  speak=rp.handler(joined,None,meetings)['Actions'][0]; self.assertEqual(speak,{'Type':'Speak','Parameters':{'Text':'Please wait while we connect you with Igor.','CallId':'leg-a-fixture','Engine':'neural','LanguageCode':'en-US','TextType':'text','VoiceId':'Joanna'}})
  response=event('CALL_UPDATE_REQUESTED',attrs); response['ActionData']={'Parameters':{'Arguments':{'Function':'Response','Text':'answer fixture'}}}; self.assertEqual(rp.handler(response,None,meetings)['Actions'][0]['Parameters']['Text'],'answer fixture')
  hangup=event('HANGUP',attrs); hangup['ActionData']={'Parameters':{'ParticipantTag':'LEG-A'}}; self.assertEqual(rp.handler(hangup,None,meetings)['Actions'],[{'Type':'Hangup','Parameters':{'SipResponseCode':'0','CallId':'leg-b-fixture'}}]); meetings.delete_meeting.assert_called_once_with(MeetingId='meeting-fixture')
 def test_bridge_invokes_existing_conversation_at_prior_bedrock_boundary(self):
  os.environ['CONVERSATION_FUNCTION_NAME']='conversation'; lam=Mock(); lam.invoke.return_value={'Payload':Mock(read=lambda:json.dumps({'body':json.dumps({'message':'answer'})}).encode())}
  result=rp.bridge({'meeting_id':'meeting-fixture','transcript':'final transcript fixture'},None,lam)
  self.assertEqual(result['response'],'answer'); payload=json.loads(lam.invoke.call_args.kwargs['Payload']); self.assertTrue(json.loads(payload['body'])['telephone'])
