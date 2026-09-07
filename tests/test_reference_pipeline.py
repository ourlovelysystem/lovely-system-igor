import importlib.util, json
from pathlib import Path
from unittest.mock import Mock
p=Path(__file__).parents[1]/'src/telephone/reference_pipeline.py'; spec=importlib.util.spec_from_file_location('rp',p); rp=importlib.util.module_from_spec(spec); spec.loader.exec_module(rp)
def event(t,attrs=None): return {'SchemaVersion':'1.0','InvocationEventType':t,'CallDetails':{'TransactionId':'tx','TransactionAttributes':attrs or {},'Participants':[{'ParticipantTag':'LEG-A','CallId':'a'},{'ParticipantTag':'LEG-B','CallId':'b'}]}}
def test_reference_inbound_join_shape():
 m=Mock();m.create_meeting_with_attendees.return_value={'Meeting':{'MeetingId':'m'},'Attendees':[{'JoinToken':'j'}]}
 out=rp.handler(event('NEW_INBOUND_CALL'),None,m); assert out['Actions']==[{'Type':'JoinChimeMeeting','Parameters':{'JoinToken':'j','CallId':'a','MeetingId':'m'}}]; assert out['TransactionAttributes']['MeetingId']=='m'
def test_reference_success_update_and_hangup_transitions():
 attrs={'MeetingId':'m','CallIdLegA':'a','CallIdLegB':'b'}; e=event('ACTION_SUCCESSFUL',attrs);e['ActionData']={'Type':'JoinChimeMeeting'}; assert rp.handler(e,None,Mock())['Actions'][0]['Type']=='Speak'
 e=event('CALL_UPDATE_REQUESTED',attrs);e['ActionData']={'Parameters':{'Arguments':{'Function':'Response','Text':'answer'}}}; assert rp.handler(e,None,Mock())['Actions'][0]['Parameters']['Text']=='answer'
 e=event('HANGUP',attrs);e['ActionData']={'Parameters':{'ParticipantTag':'LEG-A'}};m=Mock(); assert rp.handler(e,None,m)['Actions'][0]['Parameters']['CallId']=='b';m.delete_meeting.assert_called_once_with(MeetingId='m')
def test_bridge_uses_existing_conversation_boundary(monkeypatch):
 monkeypatch.setenv('CONVERSATION_FUNCTION_NAME','conversation'); l=Mock();l.invoke.return_value={'Payload':Mock(read=lambda:json.dumps({'body':json.dumps({'message':'answer'})}).encode())}; assert rp.bridge({'meeting_id':'m','transcript':'question'},None,l)['response']=='answer'; assert b'"telephone": true' in l.invoke.call_args.kwargs['Payload']
