"""Chime/Lex telephone adapter. It stores text linkage only; never audio or PINs."""
from __future__ import annotations
import hashlib, hmac, json, os, re, uuid
from datetime import UTC, datetime
from typing import Any

MUTATING = re.compile(r"\b(create|delete|remove|update|change|deploy|publish|push|commit|write|put|terminate|start|stop)\b", re.I)
CONFIRM = re.compile(r"^\s*(confirm|yes|one)\s*[.!]?\s*$", re.I)
DENY = re.compile(r"\b(no|cancel|deny|zero)\b", re.I)

def now(): return datetime.now(UTC).isoformat()
def safe_id(value: str) -> str: return hashlib.sha256(value.encode()).hexdigest()[:32]
def say(text: str) -> dict[str, Any]: return {"messages":[{"contentType":"PlainText","content":text}]}
def _secret(client: Any, name: str) -> dict[str, Any]:
    raw=client.get_secret_value(SecretId=name)["SecretString"]
    value=json.loads(raw)
    if not isinstance(value,dict): raise ValueError("telephone secret must be an object")
    return value
def _canonical_phone(value: Any) -> str:
    """Compare telephone identities in E.164 form without persisting them."""
    digits = re.sub(r"\D", "", str(value))
    # Chime supplies E.164. Accept harmless punctuation/spacing differences in the
    # runtime allowlist, but never broaden the comparison beyond the full number.
    return "+" + digits if digits else ""
def _allowed(secret: dict[str,Any], caller: str) -> bool:
    values=secret.get("allowlist", secret.get("caller_allowlist", []))
    if isinstance(values,str): values=[values]
    candidate=_canonical_phone(caller)
    return bool(candidate) and isinstance(values,list) and any(hmac.compare_digest(_canonical_phone(x), candidate) for x in values)
def _pin_ok(secret: dict[str,Any], digits: str) -> bool:
    return isinstance(secret.get("pin"),str) and hmac.compare_digest(secret["pin"],digits)
def _put_call(table:Any, call_id:str, **values:Any):
    item={"call_id":call_id,"record_key":"CALL","updated_at":now(),**values}; table.put_item(Item=item)
def _call(table:Any, call_id:str)->dict[str,Any]: return table.get_item(Key={"call_id":call_id,"record_key":"CALL"},ConsistentRead=True).get("Item",{})
def _invoke(lam:Any, name:str, event:dict[str,Any])->dict[str,Any]:
    out=lam.invoke(FunctionName=name,InvocationType="RequestResponse",Payload=json.dumps(event).encode())
    if out.get("FunctionError"): raise RuntimeError("shared Igor service failed")
    return json.loads(out["Payload"].read())
def _conversation_event(conversation_id:str, text:str)->dict[str,Any]:
    # Telephone identity is a stable pseudonym; this is the same persisted conversation engine/API.
    return {"requestContext":{"http":{"method":"POST"},"authorizer":{"jwt":{"claims":{"sub":"telephone"}}}},"rawPath":f"/conversations/{conversation_id}/messages","body":json.dumps({"message":text,"telephone":True})}
def _control_event(method:str,path:str,body:dict[str,Any])->dict[str,Any]:
    return {"requestContext":{"http":{"method":method}},"rawPath":path,"body":json.dumps(body)}
def _body(reply:dict[str,Any])->dict[str,Any]: return json.loads(reply.get("body") or "{}")
def chime(event:dict[str,Any], table:Any, secrets:Any, bot_alias_arn:str, secret_name:str)->dict[str,Any]:
    details=event.get("CallDetails",{}); call_id=details.get("TransactionId") or details.get("SessionId") or uuid.uuid4().hex
    caller=str((details.get("Participants") or [{}])[0].get("From",""))
    # Never persist caller number. An allowlisted call is represented only by its hash.
    try: authorized=_allowed(_secret(secrets,secret_name),caller)
    except Exception: authorized=False
    if not authorized: return {"Actions":[{"Type":"Speak","Parameters":{"Text":"This number is not authorized. Goodbye."}},{"Type":"Hangup","Parameters":{}}]}
    # StartBotConversation requires a real Lex V2 alias ARN. Returning it with an
    # empty endpoint causes Chime to terminate the call instead of playing a prompt.
    # Fail closed with valid PSTN actions until the bot is provisioned.
    if not bot_alias_arn.strip():
        return {"Actions":[{"Type":"Speak","Parameters":{"Text":"Telephone service is not configured. Goodbye."}},{"Type":"Hangup","Parameters":{}}]}
    _put_call(table,call_id,authentication="PIN_REQUIRED",caller_hash=safe_id(caller),raw_audio_retained=False)
    return {"Actions":[{"Type":"StartBotConversation","Parameters":{"BotAliasArn":bot_alias_arn,"LocaleId":"en_US","SessionAttributes":{"call_id":call_id}}}]}
def lex(event:dict[str,Any], table:Any, secrets:Any, lam:Any, conversation_fn:str, control_fn:str, secret_name:str)->dict[str,Any]:
    session=event.get("sessionState",{}).get("sessionAttributes") or {}; call_id=session.get("call_id",uuid.uuid4().hex)
    text=str((event.get("inputTranscript") or "")).strip(); call=_call(table,call_id)
    # Lex delivers PIN digits as transcript. Never save, log, or include it in a response.
    if call.get("authentication")!="AUTHENTICATED":
        try: ok=_pin_ok(_secret(secrets,secret_name),text)
        except Exception: ok=False
        if not ok: return say("Authentication failed. Goodbye.")
        created=_body(_invoke(lam,conversation_fn,{"requestContext":{"http":{"method":"POST"},"authorizer":{"jwt":{"claims":{"sub":"telephone"}}}},"rawPath":"/conversations","body":"{}"}))
        conversation_id=created["conversation_id"]
        _put_call(table,call_id,authentication="AUTHENTICATED",conversation_id=conversation_id,raw_audio_retained=False)
        return say("Authenticated. Ask a question, request a read only check, or state a command.")
    confidence=float(((event.get("interpretations") or [{}])[0].get("nluConfidence") or {}).get("score",1))
    if confidence < .70 or not text: return say("I did not understand that confidently. Please repeat it.")
    if DENY.search(text) and call.get("pending_command"):
        _put_call(table,call_id,authentication="AUTHENTICATED",conversation_id=call["conversation_id"],confirmation="REFUSED")
        return say("Command cancelled. No job was created.")
    if CONFIRM.match(text) and call.get("pending_command"):
        pending=call["pending_command"]
        # Atomic state transition means repeated confirmations cannot create another job.
        table.update_item(Key={"call_id":call_id,"record_key":"CALL"},UpdateExpression="SET confirmation = :confirmed, updated_at = :at REMOVE pending_command",ConditionExpression="confirmation = :pending",ExpressionAttributeValues={":confirmed":"CONFIRMED",":pending":"PENDING",":at":now()})
        reply=_body(_invoke(lam,control_fn,_control_event("POST","/jobs",{"idea":pending,"conversation_id":call["conversation_id"]})))
        _put_call(table,call_id,authentication="AUTHENTICATED",conversation_id=call["conversation_id"],confirmation="CONFIRMED",worker_job_id=reply.get("job_id"),raw_audio_retained=False)
        return say("Confirmed. I submitted one worker job. You may hang up; it will continue running.")
    if MUTATING.search(text):
        _put_call(table,call_id,authentication="AUTHENTICATED",conversation_id=call["conversation_id"],pending_command=text,confirmation="PENDING",raw_audio_retained=False)
        return say("I heard this action: "+text+". Say confirm or press one to submit exactly one worker job. Say no or press zero to cancel.")
    if re.search(r"\b(status|progress|job)\b",text,re.I) and call.get("worker_job_id"):
        reply=_body(_invoke(lam,control_fn,_control_event("GET","/jobs/"+call["worker_job_id"],{})))
        return say("Job status is "+str(reply.get("status","unavailable"))+". "+str(reply.get("current_activity",""))[:300])
    reply=_body(_invoke(lam,conversation_fn,_conversation_event(call["conversation_id"],text)))
    answer=str(reply.get("text") or reply.get("assistant_text") or "I could not produce an answer.")
    _put_call(table,call_id,authentication="AUTHENTICATED",conversation_id=call["conversation_id"],last_turn_at=now(),raw_audio_retained=False)
    return say(answer[:3000])
def handler(event:dict[str,Any], context:Any)->dict[str,Any]:
    del context
    import boto3
    table=boto3.resource("dynamodb").Table(os.environ["TELEPHONE_CALLS_TABLE"]); sec=boto3.client("secretsmanager"); lam=boto3.client("lambda")
    if "CallDetails" in event: return chime(event,table,sec,os.environ["LEX_BOT_ALIAS_ARN"],os.environ["TELEPHONE_AUTH_SECRET_NAME"])
    return lex(event,table,sec,lam,os.environ["CONVERSATION_FUNCTION_NAME"],os.environ["CONTROL_FUNCTION_NAME"],os.environ["TELEPHONE_AUTH_SECRET_NAME"])
