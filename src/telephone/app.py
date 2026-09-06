"""Chime PSTN/Lex telephone adapter; Igor remains the conversation and job engine."""
from __future__ import annotations
import hashlib, hmac, json, os, re, uuid
from datetime import UTC, datetime
from typing import Any

MUTATING = re.compile(r"\b(create|delete|remove|update|change|deploy|publish|push|commit|write|put|terminate|start|stop)\b", re.I)
CONFIRM = re.compile(r"^\s*(confirm|yes|one)\s*[.!]?\s*$", re.I)
DENY = re.compile(r"\b(no|cancel|deny|zero)\b", re.I)
MAX_PIN_ATTEMPTS = 3

def now(): return datetime.now(UTC).isoformat()
def safe_id(value: str) -> str: return hashlib.sha256(value.encode()).hexdigest()[:32]
def say(text: str) -> dict[str, Any]: return {"messages":[{"contentType":"PlainText","content":text}]}
def _secret(client: Any, name: str) -> dict[str, Any]:
    value=json.loads(client.get_secret_value(SecretId=name)["SecretString"])
    if not isinstance(value,dict): raise ValueError("telephone secret must be an object")
    return value
def _allow_any_caller(secret: dict[str,Any]) -> bool:
    """Caller identity is intentionally not an authentication factor."""
    return secret.get("allow_any_caller") is True
def _pin_ok(secret: dict[str,Any], digits: str) -> bool:
    return isinstance(secret.get("pin"),str) and hmac.compare_digest(secret["pin"],digits)
def _put_call(table:Any, call_id:str, **values:Any): table.put_item(Item={"call_id":call_id,"record_key":"CALL","updated_at":now(),**values})
def _call(table:Any, call_id:str)->dict[str,Any]: return table.get_item(Key={"call_id":call_id,"record_key":"CALL"},ConsistentRead=True).get("Item",{})
def _invoke(lam:Any, name:str, event:dict[str,Any])->dict[str,Any]:
    out=lam.invoke(FunctionName=name,InvocationType="RequestResponse",Payload=json.dumps(event).encode())
    if out.get("FunctionError"): raise RuntimeError("shared Igor service failed")
    return json.loads(out["Payload"].read())
def _body(reply:dict[str,Any])->dict[str,Any]: return json.loads(reply.get("body") or "{}")
def _conversation_event(conversation_id:str,text:str)->dict[str,Any]:
    return {"requestContext":{"http":{"method":"POST"},"authorizer":{"jwt":{"claims":{"sub":"telephone"}}}},"rawPath":f"/conversations/{conversation_id}/messages","body":json.dumps({"message":text,"telephone":True})}
def _control_event(method:str,path:str,body:dict[str,Any])->dict[str,Any]: return {"requestContext":{"http":{"method":method}},"rawPath":path,"body":json.dumps(body)}
def _call_id(event:dict[str,Any])->str:
    details=event.get("CallDetails",{}); return details.get("TransactionId") or details.get("SessionId") or uuid.uuid4().hex
def _leg_a_call_id(event: dict[str, Any]) -> str:
    """Return the inbound LEG-A CallId required by PSTN audio actions."""
    for participant in (event.get("CallDetails", {}) or {}).get("Participants", []) or []:
        if participant.get("ParticipantTag") == "LEG-A" and isinstance(participant.get("CallId"), str):
            return participant["CallId"]
    parameters = ((event.get("ActionData") or {}).get("Parameters") or {})
    if isinstance(parameters.get("CallId"), str):
        return parameters["CallId"]
    raise ValueError("Chime event has no inbound LEG-A CallId")
def _digits(event:dict[str,Any])->str:
    data=event.get("ActionData",{}); return str(data.get("ReceivedDigits") or data.get("Digits") or "").rstrip("#")

# Contract copied structurally from the documented Amazon Chime SDK PSTN Audio
# action definitions.  Keep this small allow-list next to construction so tests
# reject a tempting but unsupported action/parameter before deployment.
_ACTION_CONTRACTS = {
    "SpeakAndGetDigits": {"CallId": str, "SpeechParameters": dict, "InputDigitsRegex": str,
                            "TerminatorDigits": list, "TimeoutInSeconds": int,
                            "InBetweenDigitsTimeoutInMillis": int},
    "Speak": {"CallId": str, "SpeechParameters": dict},
    "PlayAudio": {"ParticipantTag": str, "AudioSource": dict},
    "Hangup": {"ParticipantTag": str, "SipResponseCode": str},
    "StartBotConversation": {"BotAliasArn": str, "LocaleId": str, "SessionAttributes": dict},
}
def _validate_action(action: dict[str, Any]) -> None:
    if set(action) != {"Type", "Parameters"} or action.get("Type") not in _ACTION_CONTRACTS:
        raise ValueError("unsupported Chime action")
    parameters = action["Parameters"]
    expected = _ACTION_CONTRACTS[action["Type"]]
    if not isinstance(parameters, dict) or set(parameters) != set(expected):
        raise ValueError("unsupported Chime action parameters")
    if any(not isinstance(parameters[key], kind) or (kind is int and isinstance(parameters[key], bool)) for key, kind in expected.items()):
        raise ValueError("incorrect Chime action parameter type")
    if action["Type"] in ("Speak", "SpeakAndGetDigits"):
        speech = parameters["SpeechParameters"]
        if set(speech) != {"Text"} or not isinstance(speech["Text"], str):
            raise ValueError("unsupported Chime speech parameters")
    if action["Type"] == "PlayAudio":
        audio = parameters["AudioSource"]
        if set(audio) != {"Type", "BucketName", "Key"} or audio.get("Type") != "S3" or not all(isinstance(audio.get(key), str) and audio[key] for key in ("BucketName", "Key")):
            raise ValueError("unsupported Chime audio source")
    if action["Type"] == "Hangup" and parameters["SipResponseCode"] not in {"0", "480", "486"}:
        raise ValueError("unsupported Chime SIP response code")
    if action["Type"] == "SpeakAndGetDigits" and parameters["TerminatorDigits"] != ["#"]:
        raise ValueError("unsupported Chime terminator")
def _sma(actions:list[dict[str,Any]])->dict[str,Any]:
    """Return a validated Amazon Chime SDK SIP media application response."""
    for action in actions: _validate_action(action)
    return {"SchemaVersion":"1.0","Actions":actions}
def _start_bot(call_id:str, conversation_id:str, bot_alias_arn:str)->dict[str,Any]:
    return _sma([{"Type":"StartBotConversation","Parameters":{"BotAliasArn":bot_alias_arn,"LocaleId":"en_US","SessionAttributes":{"call_id":call_id,"conversation_id":conversation_id}}}])
def _speak(call_id: str, text: str) -> dict[str, Any]:
    return {"Type":"Speak", "Parameters":{"CallId":call_id,"SpeechParameters":{"Text":text}}}
def _hangup(call_id: str, text: str) -> dict[str, Any]:
    return _sma([_speak(call_id, text), {"Type":"Hangup","Parameters":{"CallId":call_id}}])
def _diagnostic_play_audio(bucket_name: str) -> dict[str, Any]:
    """IGOR-018's exact inbound-only S3 diagnostic response."""
    if not bucket_name:
        raise ValueError("diagnostic audio bucket is not configured")
    return _sma([{"Type":"PlayAudio", "Parameters":{"ParticipantTag":"LEG-A", "AudioSource":{"Type":"S3","BucketName":bucket_name,"Key":"igor-018/diagnostic.wav"}}}])
def _diagnostic_hangup(sip_response_code: str) -> dict[str, Any]:
    """Terminate only after media success; failures use a supported SIP code."""
    return _sma([{"Type":"Hangup", "Parameters":{"ParticipantTag":"LEG-A", "SipResponseCode":sip_response_code}}])
def _pin_prompt(call_id: str, retry: bool = False) -> dict[str, Any]:
    text = "PIN was not accepted. Enter your PIN followed by pound." if retry else "Welcome to Igor. Enter your PIN followed by pound."
    return _sma([{"Type":"SpeakAndGetDigits","Parameters":{"CallId":call_id,"SpeechParameters":{"Text":text},"InputDigitsRegex":"^[0-9]{1,32}#$","TerminatorDigits":["#"],"TimeoutInSeconds":15,"InBetweenDigitsTimeoutInMillis":5000}}])
def _is_digit_result(event: dict[str, Any]) -> bool:
    data = event.get("ActionData") or {}
    return "ReceivedDigits" in data or "Digits" in data
def _attempts(call: dict[str, Any]) -> int:
    try: return max(0, int(call.get("pin_attempts", 0)))
    except (TypeError, ValueError): return 0
def chime(event:dict[str,Any], table:Any=None, secrets:Any=None, lam:Any=None, conversation_fn:str="", bot_alias_arn:str="", secret_name:str="")->dict[str,Any]:
    """IGOR-018 isolated SMA handler: no authentication or service dependency."""
    del table, secrets, lam, conversation_fn, bot_alias_arn, secret_name
    event_type = event.get("InvocationEventType", "NEW_INBOUND_CALL")
    if event_type == "NEW_INBOUND_CALL":
        return _diagnostic_play_audio(os.environ.get("DIAGNOSTIC_AUDIO_BUCKET", ""))
    if event_type == "ACTION_SUCCESSFUL":
        return _diagnostic_hangup("0")
    # Chime terminal/failure paths must still receive a documented Hangup action,
    # while staying outside authentication, media-repeat, and conversation flows.
    return _diagnostic_hangup("480")
def lex_reply(event:dict[str,Any],text:str)->dict[str,Any]:
    state=event.get("sessionState",{}); intent=(state.get("intent") or {}).get("name","IgorRelayIntent")
    attrs=state.get("sessionAttributes") or {}
    return {"sessionState":{"dialogAction":{"type":"ElicitIntent"},"intent":{"name":intent,"state":"InProgress"},"sessionAttributes":attrs},**say(text)}
def lex(event:dict[str,Any],table:Any,lam:Any,conversation_fn:str,control_fn:str)->dict[str,Any]:
    session=event.get("sessionState",{}).get("sessionAttributes") or {}; call_id=session.get("call_id",uuid.uuid4().hex)
    text=str(event.get("inputTranscript") or "").strip(); call=_call(table,call_id)
    if call.get("authentication")!="AUTHENTICATED" or not call.get("conversation_id"):
        return lex_reply(event,"Authentication is required before conversation access. Goodbye.")
    confidence=float(((event.get("interpretations") or [{}])[0].get("nluConfidence") or {}).get("score",1))
    if confidence < .70 or not text: return lex_reply(event,"I did not understand that confidently. Please repeat it.")
    if DENY.search(text) and call.get("pending_command"):
        _put_call(table,call_id,authentication="AUTHENTICATED",conversation_id=call["conversation_id"],confirmation="REFUSED",raw_audio_retained=False)
        return lex_reply(event,"Command cancelled. No job was created.")
    if CONFIRM.match(text) and call.get("pending_command"):
        pending=call["pending_command"]
        table.update_item(Key={"call_id":call_id,"record_key":"CALL"},UpdateExpression="SET confirmation = :confirmed, updated_at = :at REMOVE pending_command",ConditionExpression="confirmation = :pending",ExpressionAttributeValues={":confirmed":"CONFIRMED",":pending":"PENDING",":at":now()})
        reply=_body(_invoke(lam,control_fn,_control_event("POST","/jobs",{"idea":pending,"conversation_id":call["conversation_id"]})))
        _put_call(table,call_id,authentication="AUTHENTICATED",conversation_id=call["conversation_id"],confirmation="CONFIRMED",worker_job_id=reply.get("job_id"),raw_audio_retained=False)
        return lex_reply(event,"Confirmed. I submitted one worker job. You may hang up; it will continue running.")
    if MUTATING.search(text):
        _put_call(table,call_id,authentication="AUTHENTICATED",conversation_id=call["conversation_id"],pending_command=text,confirmation="PENDING",raw_audio_retained=False)
        return lex_reply(event,"I heard this action: "+text+". Say confirm or press one to submit exactly one worker job. Say no or press zero to cancel.")
    if re.search(r"\b(status|progress|job)\b",text,re.I) and call.get("worker_job_id"):
        reply=_body(_invoke(lam,control_fn,_control_event("GET","/jobs/"+call["worker_job_id"],{})))
        return lex_reply(event,"Job status is "+str(reply.get("status","unavailable"))+". "+str(reply.get("current_activity", ""))[:300])
    reply=_body(_invoke(lam,conversation_fn,_conversation_event(call["conversation_id"],text)))
    answer=str(reply.get("text") or reply.get("assistant_text") or "I could not produce an answer.")
    _put_call(table,call_id,authentication="AUTHENTICATED",conversation_id=call["conversation_id"],last_turn_at=now(),raw_audio_retained=False)
    return lex_reply(event,answer[:3000])
def _safe_chime_diagnostic(event: dict[str, Any]) -> None:
    """Emit only the bounded operational fields approved for IGOR-018."""
    action_data = event.get("ActionData") or {}
    diagnostic = {
        "event_type": event.get("InvocationEventType", "NEW_INBOUND_CALL"),
        "sequence": event.get("Sequence"),
        "action_type": action_data.get("Type") if isinstance(action_data, dict) else None,
        "ErrorType": event.get("ErrorType"),
        "ErrorMessage": event.get("ErrorMessage"),
    }
    print(json.dumps({"chime_diagnostic": diagnostic}))
def handler(event:dict[str,Any],context:Any)->dict[str,Any]:
    del context
    if "CallDetails" in event:
        _safe_chime_diagnostic(event)
        # The entire Chime route remains dependency-free for this physical test.
        return chime(event)
    import boto3
    table=boto3.resource("dynamodb").Table(os.environ["TELEPHONE_CALLS_TABLE"]); lam=boto3.client("lambda")
    return lex(event,table,lam,os.environ["CONVERSATION_FUNCTION_NAME"],os.environ["CONTROL_FUNCTION_NAME"])
