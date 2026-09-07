import importlib.util, json, os, unittest
from pathlib import Path
from unittest.mock import Mock
p=Path(__file__).parents[1]/'src/telephone/reference_pipeline.py'; spec=importlib.util.spec_from_file_location('rp',p); rp=importlib.util.module_from_spec(spec); spec.loader.exec_module(rp)
def event(t,attrs=None): return {'SchemaVersion':'1.0','InvocationEventType':t,'CallDetails':{'TransactionId':'tx','TransactionAttributes':attrs or {},'Participants':[{'ParticipantTag':'LEG-A','CallId':'a'},{'ParticipantTag':'LEG-B','CallId':'b'}]}}
class ReferencePipelineTests(unittest.TestCase):
 def test_full_reference_transition_fixtures(self):
  m=Mock();m.create_meeting_with_attendees.return_value={'Meeting':{'MeetingId':'m'},'Attendees':[{'JoinToken':'j'}]}; out=rp.handler(event('NEW_INBOUND_CALL'),None,m); self.assertEqual(out['Actions'],[{'Type':'JoinChimeMeeting','Parameters':{'JoinToken':'j','CallId':'a','MeetingId':'m'}}])
  attrs=out['TransactionAttributes']; e=event('ACTION_SUCCESSFUL',attrs);e['ActionData']={'Type':'JoinChimeMeeting'}; self.assertEqual(rp.handler(e,None,m)['Actions'][0]['Type'],'Speak')
  e=event('CALL_UPDATE_REQUESTED',attrs);e['ActionData']={'Parameters':{'Arguments':{'Function':'Response','Text':'answer'}}}; self.assertEqual(rp.handler(e,None,m)['Actions'][0]['Parameters']['Text'],'answer')
  e=event('HANGUP',attrs);e['ActionData']={'Parameters':{'ParticipantTag':'LEG-A'}}; self.assertEqual(rp.handler(e,None,m)['Actions'][0]['Parameters']['CallId'],'b')
 def test_bridge_invokes_existing_conversation_with_no_transcript_logging(self):
  os.environ['CONVERSATION_FUNCTION_NAME']='conversation'; l=Mock();l.invoke.return_value={'Payload':Mock(read=lambda:json.dumps({'body':json.dumps({'message':'answer'})}).encode())}; self.assertEqual(rp.bridge({'meeting_id':'m','transcript':'question'},None,l)['response'],'answer'); self.assertIn(b'"telephone": true',l.invoke.call_args.kwargs['Payload'])
