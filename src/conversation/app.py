"""Igor's persistent conversational core and bounded tool loop."""

from __future__ import annotations

import base64
import json
import os
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any


MAX_MESSAGE_LENGTH = 20_000
MAX_CONTEXT_MESSAGES = 60
MAX_TOOL_ROUNDS = 4

SYSTEM_PROMPT = """You are Igor, a private AWS-resident conversational coding and infrastructure
operator. Speak plainly and preserve conversational context. You may answer general questions without
using a tool. Your only execution capability today is submit_build, which creates one new, small,
stateless Python HTTP Lambda under Igor's verified deployment contract. Use it only when the operator
clearly asks you to build or deploy something that fits that boundary. Use get_job_status when the
operator asks about a known job. Never imply that requested work was performed unless a tool result
shows it. Report QUEUED or RUNNING as unfinished. Report WORKING only when the tool reports WORKING.
If a request needs capabilities you do not have, say exactly what is unavailable. Do not invent AWS,
GitHub, test, deployment, endpoint, or evidence results."""

TOOL_CONFIG = {
    "tools": [
        {
            "toolSpec": {
                "name": "submit_build",
                "description": (
                    "Submit a new bounded Igor build: one dependency-free, stateless Python HTTP Lambda."
                ),
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "idea": {
                                "type": "string",
                                "description": "Complete product requirement for the small HTTP service.",
                            }
                        },
                        "required": ["idea"],
                        "additionalProperties": False,
                    }
                },
            }
        },
        {
            "toolSpec": {
                "name": "get_job_status",
                "description": "Read the durable state and evidence location for an Igor job.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {"job_id": {"type": "string"}},
                        "required": ["job_id"],
                        "additionalProperties": False,
                    }
                },
            }
        },
    ]
}


class RequestError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def response(status_code: int, body: Any) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body, default=_json_default),
    }


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    raise TypeError(f"Cannot encode {type(value).__name__}")


def _request(event: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    method = (
        event.get("requestContext", {}).get("http", {}).get("method")
        or event.get("httpMethod")
        or ""
    ).upper()
    path = (event.get("rawPath") or event.get("path") or "/").rstrip("/") or "/"
    raw_body = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw_body = base64.b64decode(raw_body).decode("utf-8")
    try:
        body = json.loads(raw_body)
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError) as exc:
        raise RequestError(400, "request body must be valid JSON") from exc
    if not isinstance(body, dict):
        raise RequestError(400, "request body must be a JSON object")
    return method, path, body


def _owner_id(event: dict[str, Any]) -> str:
    claims = (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("jwt", {})
        .get("claims", {})
    )
    owner_id = claims.get("sub")
    if not owner_id:
        raise RequestError(401, "authenticated operator identity is missing")
    return owner_id


def _get_meta(table: Any, conversation_id: str, owner_id: str) -> dict[str, Any]:
    item = table.get_item(
        Key={"conversation_id": conversation_id, "record_key": "META"},
        ConsistentRead=True,
    ).get("Item")
    if not item:
        raise RequestError(404, "conversation not found")
    if item.get("owner_id") != owner_id:
        raise RequestError(404, "conversation not found")
    return item


def _put_message(
    table: Any,
    *,
    conversation_id: str,
    role: str,
    content: list[dict[str, Any]],
) -> dict[str, Any]:
    timestamp = now_iso()
    item = {
        "conversation_id": conversation_id,
        "record_key": f"MSG#{timestamp}#{uuid.uuid4().hex}",
        "created_at": timestamp,
        "role": role,
        "content_json": json.dumps(content, separators=(",", ":")),
    }
    table.put_item(Item=item)
    return item


def _load_messages(table: Any, conversation_id: str) -> list[dict[str, Any]]:
    page = table.query(
        KeyConditionExpression="conversation_id = :conversation_id AND begins_with(record_key, :prefix)",
        ExpressionAttributeValues={":conversation_id": conversation_id, ":prefix": "MSG#"},
        ScanIndexForward=False,
        Limit=MAX_CONTEXT_MESSAGES,
    )
    items = list(reversed(page.get("Items", [])))
    return [
        {"role": item["role"], "content": json.loads(item["content_json"])}
        for item in items
    ]


def _public_messages(table: Any, conversation_id: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for message in _load_messages(table, conversation_id):
        text = "".join(
            block.get("text", "") for block in message["content"] if isinstance(block, dict)
        ).strip()
        tool_names = [
            block["toolUse"]["name"]
            for block in message["content"]
            if isinstance(block, dict) and isinstance(block.get("toolUse"), dict)
        ]
        if text or tool_names:
            messages.append({"role": message["role"], "text": text, "tools": tool_names})
    return messages


def _invoke_control(lambda_client: Any, function_name: str, method: str, path: str, body: Any) -> Any:
    event = {
        "requestContext": {"http": {"method": method}},
        "rawPath": path,
        "body": json.dumps(body),
    }
    invocation = lambda_client.invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",
        Payload=json.dumps(event).encode("utf-8"),
    )
    if invocation.get("FunctionError"):
        raise RuntimeError(f"control function failed: {invocation['FunctionError']}")
    payload = json.loads(invocation["Payload"].read())
    body_value = json.loads(payload.get("body") or "{}")
    if not 200 <= int(payload.get("statusCode", 500)) < 300:
        raise RuntimeError(body_value.get("error") or "control request failed")
    return body_value


def _run_tool(lambda_client: Any, function_name: str, name: str, inputs: Any) -> Any:
    if not isinstance(inputs, dict):
        raise ValueError("tool input must be an object")
    if name == "submit_build":
        idea = inputs.get("idea")
        if not isinstance(idea, str) or not idea.strip():
            raise ValueError("submit_build requires a non-empty idea")
        return _invoke_control(lambda_client, function_name, "POST", "/jobs", {"idea": idea})
    if name == "get_job_status":
        job_id = inputs.get("job_id")
        if not isinstance(job_id, str) or not job_id or "/" in job_id:
            raise ValueError("get_job_status requires a valid job_id")
        return _invoke_control(lambda_client, function_name, "GET", f"/jobs/{job_id}", {})
    raise ValueError(f"unknown tool: {name}")


def converse(
    *,
    table: Any,
    bedrock: Any,
    lambda_client: Any,
    control_function_name: str,
    model_id: str,
    conversation_id: str,
) -> dict[str, Any]:
    messages = _load_messages(table, conversation_id)
    tool_events: list[dict[str, Any]] = []

    for _ in range(MAX_TOOL_ROUNDS):
        result = bedrock.converse(
            modelId=model_id,
            system=[{"text": SYSTEM_PROMPT}],
            messages=messages,
            toolConfig=TOOL_CONFIG,
            inferenceConfig={"maxTokens": 3000},
        )
        assistant = result.get("output", {}).get("message", {})
        content = assistant.get("content", [])
        if not isinstance(content, list) or not content:
            raise RuntimeError("model returned no conversational content")
        _put_message(
            table,
            conversation_id=conversation_id,
            role="assistant",
            content=content,
        )
        messages.append({"role": "assistant", "content": content})

        tool_uses = [
            block["toolUse"]
            for block in content
            if isinstance(block, dict) and isinstance(block.get("toolUse"), dict)
        ]
        if not tool_uses:
            text = "".join(
                block.get("text", "") for block in content if isinstance(block, dict)
            ).strip()
            if not text:
                raise RuntimeError("model returned no text")
            return {"text": text, "tool_events": tool_events}

        tool_results: list[dict[str, Any]] = []
        for tool_use in tool_uses:
            name = tool_use.get("name", "unknown")
            try:
                output = _run_tool(
                    lambda_client,
                    control_function_name,
                    name,
                    tool_use.get("input", {}),
                )
                status = "success"
            except Exception as exc:
                output = {"error": str(exc)[:1000]}
                status = "error"
            tool_events.append({"name": name, "status": status, "result": output})
            tool_results.append(
                {
                    "toolResult": {
                        "toolUseId": tool_use["toolUseId"],
                        "content": [{"json": output}],
                        "status": status,
                    }
                }
            )

        _put_message(
            table,
            conversation_id=conversation_id,
            role="user",
            content=tool_results,
        )
        messages.append({"role": "user", "content": tool_results})

    raise RuntimeError("model exceeded the tool-use round limit")


def handle(
    event: dict[str, Any],
    *,
    table: Any,
    bedrock: Any,
    lambda_client: Any,
    control_function_name: str,
    model_id: str,
) -> dict[str, Any]:
    try:
        method, path, body = _request(event)
        owner_id = _owner_id(event)

        if method == "POST" and path == "/conversations":
            conversation_id = uuid.uuid4().hex
            timestamp = now_iso()
            item = {
                "conversation_id": conversation_id,
                "record_key": "META",
                "owner_id": owner_id,
                "title": "New conversation",
                "created_at": timestamp,
                "updated_at": timestamp,
            }
            table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(conversation_id)",
            )
            return response(201, item)

        if method == "GET" and path == "/conversations":
            page = table.scan(
                FilterExpression="record_key = :meta AND owner_id = :owner",
                ExpressionAttributeValues={":meta": "META", ":owner": owner_id},
            )
            conversations = page.get("Items", [])
            conversations.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
            return response(200, {"conversations": conversations[:100]})

        parts = path.strip("/").split("/")
        if len(parts) == 2 and parts[0] == "conversations" and method == "GET":
            meta = _get_meta(table, parts[1], owner_id)
            return response(
                200,
                {"conversation": meta, "messages": _public_messages(table, parts[1])},
            )

        if (
            len(parts) == 3
            and parts[0] == "conversations"
            and parts[2] == "messages"
            and method == "POST"
        ):
            conversation_id = parts[1]
            meta = _get_meta(table, conversation_id, owner_id)
            text = body.get("message")
            if not isinstance(text, str) or not text.strip():
                raise RequestError(400, "message must be a non-empty string")
            text = text.strip()
            if len(text) > MAX_MESSAGE_LENGTH:
                raise RequestError(400, f"message exceeds {MAX_MESSAGE_LENGTH} characters")

            _put_message(
                table,
                conversation_id=conversation_id,
                role="user",
                content=[{"text": text}],
            )
            timestamp = now_iso()
            update = "SET updated_at = :updated"
            values: dict[str, Any] = {":updated": timestamp}
            if meta.get("title") == "New conversation":
                update += ", title = :title"
                values[":title"] = text[:80]
            table.update_item(
                Key={"conversation_id": conversation_id, "record_key": "META"},
                UpdateExpression=update,
                ExpressionAttributeValues=values,
            )

            result = converse(
                table=table,
                bedrock=bedrock,
                lambda_client=lambda_client,
                control_function_name=control_function_name,
                model_id=model_id,
                conversation_id=conversation_id,
            )
            return response(200, {"conversation_id": conversation_id, **result})

        raise RequestError(404, "not found")
    except RequestError as exc:
        return response(exc.status_code, {"error": str(exc)})
    except Exception as exc:
        return response(500, {"error": f"conversation failed: {str(exc)[:1000]}"})


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    del context
    import boto3

    return handle(
        event,
        table=boto3.resource("dynamodb").Table(os.environ["CONVERSATIONS_TABLE"]),
        bedrock=boto3.client("bedrock-runtime"),
        lambda_client=boto3.client("lambda"),
        control_function_name=os.environ["CONTROL_FUNCTION_NAME"],
        model_id=os.environ["DEFAULT_MODEL_ID"],
    )
