"""IGOR-018 reference media boundary: DTMF gate, signed assertion, and one-shot confirmation."""
from __future__ import annotations
import base64, hashlib, hmac, json, os, re, time, uuid
from datetime import UTC, datetime
from typing import Any

MAX_PIN_ATTEMPTS=3; ASSERTION_SECONDS=900; CONFIRM_SECONDS=300
MUTATING=re.compile(r"\b(create|delete|remove|update|change|deploy|publish|push|commit|write|put|terminate|start|stop|infrastructure|code)\b",re.I)
CONFIRM=re.compile(r"^\s*(confirm|yes|one)\s*[.!]?\s*$",re.I)
DENY=re.compile(r"\b(no|cancel|deny|zero)\b",re.I)
REQUIRED_RUNTIME_ENV=("TELEPHONE_AUTH_SECRET_NAME","TELEPHONE_CALLS_TABLE","CONTROL_FUNCTION_NAME","CONVERSATION_FUNCTION_NAME")
def _opaque(v:str)->str:return hashlib.sha256(v.encode()).hexdigest()[:32]
def _action(t:str,p:dict[str,Any])->dict[str,Any]:return {"Type":t,"Parameters":p}
def _response(a:list[dict[str,Any]],x:dict[str,str])->dict[str,Any]:return {"SchemaVersion":"1.0","Actions":a,"TransactionAttributes":x}
def _attrs(e:dict[str,Any])->dict[str,str]:
 a=dict((e.get("CallDetails")or{}).get("TransactionAttributes")or{});return {k:str(a.get(k)or"")for k in("MeetingId","CallIdLegA","CallIdLegB","IgorConversationId")}
def _leg(e:dict[str,Any],tag:str)->str:
 for p in (e.get("CallDetails")or{}).get("Participants")or[]:
  if p.get("ParticipantTag")==tag and isinstance(p.get("CallId"),str):return p["CallId"]
 return ""
def _speak(text:str,call_id:str)->dict[str,Any]:return _action("Speak",{"Text":text,"CallId":call_id,"Engine":"neural","LanguageCode":"en-US","TextType":"text","VoiceId":"Joanna"})
def _speech(text:str)->dict[str,str]:
 return {"Text":text,"Engine":"neural","LanguageCode":"en-US","TextType":"text","VoiceId":"Joanna"}
def _prompt(call_id:str,retry=False)->dict[str,Any]:
 text="PIN was not accepted. Enter your PIN followed by pound." if retry else "Welcome to Igor. Enter your PIN followed by pound."
 # SpeakAndGetDigits uses milliseconds for its required repeat duration.  The
 # former 15-second PIN window is therefore 15,000 milliseconds.
 return _response([_action("SpeakAndGetDigits",{"CallId":call_id,"SpeechParameters":_speech(text),"FailureSpeechParameters":_speech("PIN entry timed out or was invalid. Please try again."),"InputDigitsRegex":"^[0-9]{1,32}$","MinNumberOfDigits":1,"MaxNumberOfDigits":32,"TerminatorDigits":["#"],"InBetweenDigitsDurationInMilliseconds":5000,"Repeat":MAX_PIN_ATTEMPTS,"RepeatDurationInMilliseconds":15000})],{})
def _secret(c:Any)->dict[str,Any]:return json.loads(c.get_secret_value(SecretId=os.environ["TELEPHONE_AUTH_SECRET_NAME"])["SecretString"])
def _configured()->bool:return all(os.environ.get(name) for name in REQUIRED_RUNTIME_ENV)
def _configuration_failure(event:dict[str,Any],attrs:dict[str,str])->dict[str,Any]:
 return _response([_speak("Telephone service configuration is unavailable.",_leg(event,"LEG-A")),_action("Hangup",{"SipResponseCode":"0","CallId":_leg(event,"LEG-A")})],attrs)
def _assertion(call_id:str,conversation_id:str,pin:str)->str:
 raw=json.dumps({"v":1,"call_id":call_id,"conversation_id":conversation_id,"exp":int(time.time()+ASSERTION_SECONDS)},sort_keys=True,separators=(",", ":")).encode()
 return base64.urlsafe_b64encode(raw).decode().rstrip("=")+"."+hmac.new(pin.encode(),raw,hashlib.sha256).hexdigest()
def _digits(e:dict[str,Any])->str:return str((e.get("ActionData")or{}).get("ReceivedDigits")or(e.get("ActionData")or{}).get("Digits")or"").rstrip("#")
def _link(table:Any,meeting:str)->dict[str,Any]:
 r=table.query(IndexName="MeetingIdIndex",KeyConditionExpression="meeting_id = :m",ExpressionAttributeValues={":m":meeting},ConsistentRead=False);return (r.get("Items")or[{}])[0]
def _safe_chime_diagnostic(event:dict[str,Any])->None:
 # Preserve the non-sensitive lifecycle evidence used to diagnose Chime actions.
 data=event.get("ActionData") if isinstance(event.get("ActionData"),dict) else {}
 print(json.dumps({"chime_diagnostic":{"InvocationEventType":event.get("InvocationEventType"),"Sequence":event.get("Sequence"),"ActionType":data.get("Type"),"ErrorType":data.get("ErrorType"),"ErrorMessage":data.get("ErrorMessage")}}))
def _safe_auth_diagnostic(event:dict[str,Any],auth_outcome:str,call_correlation:str,next_action:str)->None:
 # Never log the event, PIN/digits, caller data, transaction attributes,
 # assertions, or transcript in the authentication transition record.
 print(json.dumps({"chime_diagnostic":{"auth_outcome":auth_outcome,"call_correlation":call_correlation,"next_action":next_action,"invocation_event_type":event.get("InvocationEventType"),"invocation_sequence":event.get("Sequence")}}))
def handler(event:dict[str,Any],context:Any,meetings:Any=None,table:Any=None,secrets:Any=None)->dict[str,Any]:
 _safe_chime_diagnostic(event)
 typ=event.get("InvocationEventType"); attrs=_attrs(event); tx=str((event.get("CallDetails")or{}).get("TransactionId")or""); call_id=_opaque(tx); leg=_leg(event,"LEG-A")
 if not _configured():return _configuration_failure(event,attrs)
 table=table or __import__('boto3').resource('dynamodb').Table(os.environ['TELEPHONE_CALLS_TABLE']); secrets=secrets or __import__('boto3').client('secretsmanager')
 if typ=="NEW_INBOUND_CALL":
  try: enabled=_secret(secrets).get("allow_any_caller") is True
  except Exception: enabled=False
  if not enabled:return _response([_speak("Telephone authentication is unavailable.",leg),_action("Hangup",{"SipResponseCode":"0","CallId":leg})],attrs)
  table.put_item(Item={"call_id":call_id,"record_key":"CALL","authentication":"PIN_REQUIRED","pin_attempts":0,"updated_at":datetime.now(UTC).isoformat(),"raw_audio_retained":False})
  return _prompt(leg)
 if typ=="ACTION_SUCCESSFUL" and ((event.get("ActionData")or{}).get("Type")=="SpeakAndGetDigits" or _digits(event)):
  call=table.get_item(Key={"call_id":call_id,"record_key":"CALL"},ConsistentRead=True).get("Item",{}); sec=_secret(secrets); ok=call.get("authentication")=="PIN_REQUIRED" and isinstance(sec.get("pin"),str) and hmac.compare_digest(sec['pin'],_digits(event))
  if not ok:
   n=int(call.get("pin_attempts",0))+1
   if n>=MAX_PIN_ATTEMPTS:
    _safe_auth_diagnostic(event,"REJECTED",call_id,"Speak")
    return _response([_speak("Authentication failed. Goodbye.",leg),_action("Hangup",{"SipResponseCode":"0","CallId":leg})],attrs)
   table.update_item(Key={"call_id":call_id,"record_key":"CALL"},UpdateExpression="SET pin_attempts=:n",ExpressionAttributeValues={":n":n})
   _safe_auth_diagnostic(event,"REJECTED",call_id,"SpeakAndGetDigits")
   return _prompt(leg,True)
  client=meetings or __import__('boto3').client('chime-sdk-meetings',region_name='us-east-1'); out=client.create_meeting_with_attendees(ClientRequestToken=str(uuid.uuid4()),MediaRegion='us-east-1',ExternalMeetingId='MediaStreams',Attendees=[{"ExternalUserId":str(uuid.uuid4())}]); meeting=out['Meeting']['MeetingId']; conv=_opaque(tx or meeting); assertion=_assertion(call_id,conv,sec['pin'])
  attrs.update(MeetingId=meeting,CallIdLegA=leg,IgorConversationId=conv); table.put_item(Item={"call_id":call_id,"record_key":"CALL","meeting_id":meeting,"conversation_id":conv,"authentication":"AUTHENTICATED","authenticated_assertion":assertion,"assertion_expires_at":int(time.time()+ASSERTION_SECONDS),"updated_at":datetime.now(UTC).isoformat(),"raw_audio_retained":False})
  # AWS documents an ordered Actions list; Speak is deliberately first so the
  # caller hears acknowledgement before the existing meeting join action.
  _safe_auth_diagnostic(event,"ACCEPTED",call_id,"Speak")
  return _response([_speak("PIN accepted. Connecting you to Igor.",leg),_action("JoinChimeMeeting",{"JoinToken":out['Attendees'][0]['JoinToken'],"CallId":leg,"MeetingId":meeting})],attrs)
 if typ=="CALL_UPDATE_REQUESTED" and ((event.get("ActionData")or{}).get("Parameters")or{}).get("Arguments",{}).get("Function")=="Response":return _response([_speak(str(((event.get('ActionData')or{}).get('Parameters')or{}).get('Arguments',{}).get('Text')or'Execution service is unavailable.'),attrs['CallIdLegA'])],attrs)
 return _response([],attrs)
def bridge(event:dict[str,Any],context:Any,lam:Any=None,table:Any=None)->dict[str,Any]:
 if not _configured():return {"conversation_id":"","response":"Telephone service configuration is unavailable."}
 transcript=str(event.get('transcript')or'').strip(); meeting=str(event.get('meeting_id')or''); table=table or __import__('boto3').resource('dynamodb').Table(os.environ['TELEPHONE_CALLS_TABLE']); call=_link(table,meeting)
 if not transcript or call.get('authentication')!='AUTHENTICATED' or int(call.get('assertion_expires_at',0))<time.time():return {"conversation_id":call.get('conversation_id',''),"response":"Authentication is required before execution tools are available."}
 conv=call['conversation_id']; client=lam or __import__('boto3').client('lambda')
 if DENY.search(transcript) and call.get('confirmation')=='PENDING':
  table.update_item(Key={"call_id":call['call_id'],"record_key":"CALL"},UpdateExpression="SET confirmation=:x REMOVE pending_action,pending_expires_at",ExpressionAttributeValues={":x":"REFUSED"});return {"conversation_id":conv,"response":"Command cancelled. No job was created."}
 if CONFIRM.match(transcript):
  if call.get('confirmation')!='PENDING' or int(call.get('pending_expires_at',0))<time.time():return {"conversation_id":conv,"response":"There is no current action to confirm."}
  try:table.update_item(Key={"call_id":call['call_id'],"record_key":"CALL"},UpdateExpression="SET confirmation=:s",ConditionExpression="confirmation=:p AND conversation_id=:c AND pending_expires_at >= :n",ExpressionAttributeValues={":s":"SUBMITTING",":p":"PENDING",":c":conv,":n":int(time.time())})
  except Exception:return {"conversation_id":conv,"response":"That confirmation was already processed or no longer valid."}
  payload={"requestContext":{"http":{"method":"POST"}},"rawPath":"/jobs","body":json.dumps({"idea":call['pending_action'],"conversation_id":conv,"task_type":"general_aws"})}; out=client.invoke(FunctionName=os.environ['CONTROL_FUNCTION_NAME'],InvocationType='RequestResponse',Payload=json.dumps(payload).encode())
  if out.get('FunctionError'):return {"conversation_id":conv,"response":"Execution failed before submission; no duplicate will be submitted."}
  body=json.loads(json.loads(out['Payload'].read()).get('body')or'{}'); job=body.get('job_id')
  if not job:return {"conversation_id":conv,"response":"Execution service is genuinely unavailable; no job was submitted."}
  table.update_item(Key={"call_id":call['call_id'],"record_key":"CALL"},UpdateExpression="SET confirmation=:c, worker_job_id=:j REMOVE pending_action,pending_expires_at",ExpressionAttributeValues={":c":"SUBMITTED",":j":job});return {"conversation_id":conv,"response":f"Confirmed. Submitted exactly one job: {job}."}
 if MUTATING.search(transcript):
  table.update_item(Key={"call_id":call['call_id'],"record_key":"CALL"},UpdateExpression="SET confirmation=:p,pending_action=:a,pending_expires_at=:e",ExpressionAttributeValues={":p":"PENDING",":a":transcript,":e":int(time.time()+CONFIRM_SECONDS)});return {"conversation_id":conv,"response":"I heard an infrastructure or coding action. Confirmation is required. Say confirm or press one to submit exactly one job."}
 payload={"requestContext":{"http":{"method":"POST"},"authorizer":{"jwt":{"claims":{"sub":"telephone"}}}},"rawPath":f"/conversations/{conv}/messages","body":json.dumps({"message":transcript,"telephone":True,"telephone_assertion":call['authenticated_assertion']})}; out=client.invoke(FunctionName=os.environ['CONVERSATION_FUNCTION_NAME'],InvocationType='RequestResponse',Payload=json.dumps(payload).encode())
 if out.get('FunctionError'):return {"conversation_id":conv,"response":"Conversation service is genuinely unavailable."}
 envelope=json.loads(out['Payload'].read()); body=json.loads(envelope.get('body')or'{}');return {"conversation_id":conv,"response":str(body.get('text')or'Conversation service is genuinely unavailable.')}
