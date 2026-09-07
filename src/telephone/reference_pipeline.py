"""IGOR-018 additive compatibility layer ported from gate1-green reference contracts.
It is deliberately not attached to a SIP rule in this deployment."""
from __future__ import annotations
import hashlib, json, os, uuid
from datetime import UTC, datetime
from typing import Any

def _opaque(v:str)->str: return hashlib.sha256(v.encode()).hexdigest()[:32]
def _action(t:str,p:dict[str,Any])->dict[str,Any]: return {"Type":t,"Parameters":p}
def _response(actions:list[dict[str,Any]], attrs:dict[str,str])->dict[str,Any]: return {"SchemaVersion":"1.0","Actions":actions,"TransactionAttributes":attrs}
def _attrs(event:dict[str,Any])->dict[str,str]:
    attrs=dict((event.get("CallDetails") or {}).get("TransactionAttributes") or {})
    return {"MeetingId":str(attrs.get("MeetingId") or ""),"CallIdLegA":str(attrs.get("CallIdLegA") or ""),"CallIdLegB":str(attrs.get("CallIdLegB") or ""),"IgorConversationId":str(attrs.get("IgorConversationId") or "")}
def _leg(event:dict[str,Any],tag:str)->str:
    for p in (event.get("CallDetails") or {}).get("Participants") or []:
        if p.get("ParticipantTag")==tag and isinstance(p.get("CallId"),str): return p["CallId"]
    return ""
def _speak(text:str, call_id:str)->dict[str,Any]:
    # Exact gate1-green shape, not the prior direct-SMA SpeechParameters shape.
    return _action("Speak",{"Text":text,"CallId":call_id,"Engine":"neural","LanguageCode":"en-US","TextType":"text","VoiceId":"Joanna"})
def _put_link(table: Any, transaction_id: str, meeting_id: str, conversation_id: str) -> None:
    """Persist only opaque identifiers; never persist caller identity, audio, or transcript."""
    if table:
        table.put_item(Item={
            "call_id": _opaque(transaction_id), "record_key": "CALL", "meeting_id": meeting_id,
            "conversation_id": conversation_id, "media_state": "JOIN_REQUESTED",
            "updated_at": datetime.now(UTC).isoformat(),
        })

def handler(event:dict[str,Any], context:Any, meetings:Any=None, table:Any=None)->dict[str,Any]:
    """Reference transitions: inbound->JoinChimeMeeting; update Response->Speak; hangup."""
    typ=event.get("InvocationEventType"); attrs=_attrs(event)
    if typ=="NEW_INBOUND_CALL":
        client=meetings or __import__('boto3').client('chime-sdk-meetings',region_name='us-east-1')
        out=client.create_meeting_with_attendees(ClientRequestToken=str(uuid.uuid4()),MediaRegion='us-east-1',ExternalMeetingId='MediaStreams',Attendees=[{"ExternalUserId":str(uuid.uuid4())}])
        meeting=out["Meeting"]["MeetingId"]; leg=_leg(event,"LEG-A")
        attrs.update(MeetingId=meeting,CallIdLegA=leg,IgorConversationId=_opaque(event.get("CallDetails",{}).get("TransactionId",meeting)))
        _put_link(table, str(event["CallDetails"]["TransactionId"]), meeting, attrs["IgorConversationId"])
        return _response([_action("JoinChimeMeeting",{"JoinToken":out["Attendees"][0]["JoinToken"],"CallId":leg,"MeetingId":meeting})],attrs)
    if typ=="ACTION_SUCCESSFUL" and (event.get("ActionData") or {}).get("Type")=="JoinChimeMeeting":
        attrs["CallIdLegA"]=_leg(event,"LEG-A") or attrs["CallIdLegA"]; attrs["CallIdLegB"]=_leg(event,"LEG-B") or attrs["CallIdLegB"]
        return _response([_speak("Please wait while we connect you with Igor.",attrs["CallIdLegA"])],attrs)
    if typ=="CALL_UPDATE_REQUESTED" and ((event.get("ActionData") or {}).get("Parameters") or {}).get("Arguments",{}).get("Function")=="Response":
        text=((event["ActionData"]["Parameters"]["Arguments"].get("Text") or "I am sorry, I could not prepare a response."))
        return _response([_speak(text,attrs["CallIdLegA"])],attrs)
    if typ=="HANGUP":
        # Preserve the durable ledger for evidence/rollback; record terminal state without raw call IDs.
        if table and event.get("CallDetails", {}).get("TransactionId"):
            table.update_item(Key={"call_id": _opaque(str(event["CallDetails"]["TransactionId"])), "record_key": "CALL"}, UpdateExpression="SET media_state=:state, updated_at=:updated", ExpressionAttributeValues={":state": "HANGUP", ":updated": datetime.now(UTC).isoformat()})
        if attrs["MeetingId"]:
            (meetings or __import__('boto3').client('chime-sdk-meetings',region_name='us-east-1')).delete_meeting(MeetingId=attrs["MeetingId"])
        return _response([_action("Hangup",{"SipResponseCode":"0","CallId":attrs["CallIdLegB"]})] if (event.get("ActionData") or {}).get("Parameters",{}).get("ParticipantTag")=="LEG-A" and attrs["CallIdLegB"] else [],attrs)
    return _response([],attrs)

def bridge(event:dict[str,Any], context:Any, lam:Any=None)->dict[str,Any]:
    """Consumer replacement boundary: final transcript -> existing Igor conversation -> plain response."""
    transcript=str(event.get("transcript") or "").strip()
    conversation_id=str(event.get("conversation_id") or _opaque(str(event.get("meeting_id") or "")))
    if not transcript: return {"conversation_id":conversation_id,"response":""}
    function=os.environ["CONVERSATION_FUNCTION_NAME"]
    payload={"requestContext":{"http":{"method":"POST"},"authorizer":{"jwt":{"claims":{"sub":"telephone"}}}},"rawPath":f"/conversations/{conversation_id}/messages","body":json.dumps({"message":transcript,"telephone":True})}
    client=lam or __import__('boto3').client('lambda')
    out=client.invoke(FunctionName=function,InvocationType="RequestResponse",Payload=json.dumps(payload).encode())
    if out.get("FunctionError"): raise RuntimeError("Igor conversation invocation failed")
    body=json.loads(json.loads(out["Payload"].read()).get("body") or "{}")
    return {"conversation_id":conversation_id,"response":str(body.get("message") or body.get("response") or "I am sorry, I could not prepare a response.")}
