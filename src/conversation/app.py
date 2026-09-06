"""Igor's persistent conversational core and bounded tool loop."""

from __future__ import annotations

import base64
import json
import os
import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any


MAX_MESSAGE_LENGTH = 20_000
MAX_CONTEXT_MESSAGES = 60
MAX_TOOL_ROUNDS = 4
MAX_ATTACHMENTS_PER_MESSAGE = 20
MAX_UPLOAD_BYTES = 5 * 1024**3 * 10_000
DEFAULT_PART_SIZE = 100 * 1024**2
MAX_PART_SIZE = 5 * 1024**3
INLINE_IMAGE_BYTES = 3_500_000
INLINE_DOCUMENT_BYTES = 20_000_000
MAX_INLINE_ATTACHMENT_BYTES = 20_000_000
BYTES_MARKER = "__igor_bytes_base64_v1__"

IMAGE_FORMATS = {
    "image/gif": "gif",
    "image/jpeg": "jpeg",
    "image/jpg": "jpeg",
    "image/png": "png",
    "image/webp": "webp",
}
DOCUMENT_FORMATS = {
    ".csv": "csv",
    ".doc": "doc",
    ".docx": "docx",
    ".html": "html",
    ".md": "md",
    ".pdf": "pdf",
    ".txt": "txt",
    ".xls": "xls",
    ".xlsx": "xlsx",
}

SYSTEM_PROMPT = """You are Igor, Will Daly's private AWS-resident conversational coding and
infrastructure worker. Will directs the work. Speak plainly, preserve conversational context, and use
your own implementation judgment when his requested outcome leaves details open. Answer ordinary
questions conversationally. When Will directs you to create, change, inspect, diagnose, test, repair,
or remove software or AWS infrastructure, use execute_task with his complete objective. Do not replace
his objective with a smaller preapproved task and do not ask him to operate AWS for you. Use
get_job_status for a known job. Never imply that work was performed unless a tool result proves it.
QUEUED and RUNNING are unfinished. WORKING requires recorded execution and verification evidence.
Report BLOCKED, FAILED, or INCOMPLETE plainly. Do not invent AWS, GitHub, test, deployment, endpoint,
or evidence results. The operator may attach files. Image and document blocks are the files themselves.
An attachment manifest gives the private S3 location for every attachment. If a file is too large or
not a model-supported format, use execute_task so the worker can inspect it directly in S3."""

TOOL_CONFIG = {
    "tools": [
        {
            "toolSpec": {
                "name": "execute_task",
                "description": (
                    "Submit the operator's general coding or AWS objective to Igor's isolated execution "
                    "worker. The worker can inspect AWS, write code, run commands, create or change "
                    "infrastructure, test the result, and preserve evidence."
                ),
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "objective": {
                                "type": "string",
                                "description": "The operator's complete requested outcome and constraints.",
                            }
                        },
                        "required": ["objective"],
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


def _content_json_default(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray)):
        return {BYTES_MARKER: base64.b64encode(bytes(value)).decode("ascii")}
    raise TypeError(f"Cannot encode conversation content of type {type(value).__name__}")


def _content_json_object_hook(value: dict[str, Any]) -> Any:
    if set(value) == {BYTES_MARKER} and isinstance(value[BYTES_MARKER], str):
        return base64.b64decode(value[BYTES_MARKER], validate=True)
    return value


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
    display_text: str | None = None,
    attachments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    timestamp = now_iso()
    item = {
        "conversation_id": conversation_id,
        "record_key": f"MSG#{timestamp}#{uuid.uuid4().hex}",
        "created_at": timestamp,
        "role": role,
        "content_json": json.dumps(
            content,
            separators=(",", ":"),
            default=_content_json_default,
        ),
    }
    if display_text is not None:
        item["display_text"] = display_text
    if attachments:
        item["attachments_json"] = json.dumps(attachments, separators=(",", ":"))
    table.put_item(Item=item)
    return item


def _message_items(table: Any, conversation_id: str) -> list[dict[str, Any]]:
    page = table.query(
        KeyConditionExpression="conversation_id = :conversation_id AND begins_with(record_key, :prefix)",
        ExpressionAttributeValues={":conversation_id": conversation_id, ":prefix": "MSG#"},
        ScanIndexForward=False,
        Limit=MAX_CONTEXT_MESSAGES,
    )
    return list(reversed(page.get("Items", [])))


def _load_messages(table: Any, conversation_id: str) -> list[dict[str, Any]]:
    items = _message_items(table, conversation_id)
    messages: list[dict[str, Any]] = []
    for item in items:
        content = json.loads(
            item["content_json"],
            object_hook=_content_json_object_hook,
        )
        # Releases before the byte-source fix persisted Bedrock s3Location
        # blocks. The OpenAI model rejects those blocks, so retain the manifest
        # text and omit only the incompatible historical media block.
        content = [
            block
            for block in content
            if not (
                isinstance(block, dict)
                and isinstance(block.get("image") or block.get("document"), dict)
                and "s3Location" in (block.get("image") or block.get("document"))["source"]
            )
        ]
        messages.append({"role": item["role"], "content": content})
    return messages


def _public_messages(table: Any, conversation_id: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for item in _message_items(table, conversation_id):
        content = json.loads(item["content_json"], object_hook=_content_json_object_hook)
        text = item.get("display_text")
        if text is None:
            text = "".join(
                block.get("text", "") for block in content if isinstance(block, dict)
            ).strip()
        tool_names = [
            block["toolUse"]["name"]
            for block in content
            if isinstance(block, dict) and isinstance(block.get("toolUse"), dict)
        ]
        attachments = json.loads(item.get("attachments_json", "[]"))
        if text or tool_names or attachments:
            messages.append(
                {
                    "role": item["role"],
                    "text": text,
                    "tools": tool_names,
                    "attachments": attachments,
                }
            )
    return messages


def _safe_filename(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RequestError(400, "filename must be a non-empty string")
    name = value.strip().replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"[^A-Za-z0-9._()\[\] -]", "_", name)[:240]
    if not name or name in {".", ".."}:
        raise RequestError(400, "filename is invalid")
    return name


def _part_size(size: int) -> int:
    required = (size + 9_999) // 10_000
    mebibyte = 1024**2
    selected = max(DEFAULT_PART_SIZE, ((required + mebibyte - 1) // mebibyte) * mebibyte)
    if selected > MAX_PART_SIZE:
        raise RequestError(400, "file exceeds the S3 multipart upload limit")
    return selected


def _attachment_key(owner_id: str, conversation_id: str, attachment_id: str, name: str) -> str:
    return f"attachments/{owner_id}/{conversation_id}/{attachment_id}/{name}"


def _get_attachment(table: Any, conversation_id: str, attachment_id: str) -> dict[str, Any]:
    item = table.get_item(
        Key={"conversation_id": conversation_id, "record_key": f"ATTACH#{attachment_id}"},
        ConsistentRead=True,
    ).get("Item")
    if not item:
        raise RequestError(404, "attachment not found")
    return item


def _ready_attachments(
    table: Any, conversation_id: str, attachment_ids: Any
) -> list[dict[str, Any]]:
    if attachment_ids is None:
        return []
    if not isinstance(attachment_ids, list) or len(attachment_ids) > MAX_ATTACHMENTS_PER_MESSAGE:
        raise RequestError(
            400, f"attachment_ids must contain at most {MAX_ATTACHMENTS_PER_MESSAGE} items"
        )
    attachments: list[dict[str, Any]] = []
    seen: set[str] = set()
    for attachment_id in attachment_ids:
        if not isinstance(attachment_id, str) or not attachment_id or "/" in attachment_id:
            raise RequestError(400, "attachment id is invalid")
        if attachment_id in seen:
            continue
        seen.add(attachment_id)
        item = _get_attachment(table, conversation_id, attachment_id)
        if item.get("status") != "READY":
            raise RequestError(409, f"attachment {attachment_id} is not ready")
        attachments.append(
            {
                "attachment_id": attachment_id,
                "filename": item["filename"],
                "content_type": item["content_type"],
                "size": int(item["size"]),
                "s3_uri": item["s3_uri"],
                "s3_key": item["s3_key"],
            }
        )
    return attachments


def _document_name(filename: str) -> str:
    stem = filename.rsplit(".", 1)[0]
    cleaned = re.sub(r"[^A-Za-z0-9 ()\[\]-]", " ", stem)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return (cleaned or "attachment")[:120]


def _attachment_content(text: str, attachments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [{"text": text}]
    if not attachments:
        return content
    manifest = ["Operator attachments (private S3 objects):"]
    for attachment in attachments:
        manifest.append(
            f"- {attachment['filename']} | {attachment['content_type']} | "
            f"{attachment['size']} bytes | {attachment['s3_uri']}"
        )
    content.insert(1, {"text": "\n".join(manifest)})
    return content


def _model_attachment_blocks(
    s3: Any,
    bucket: str,
    attachments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Load only model-sized files; keep their bytes out of DynamoDB history."""
    blocks: list[dict[str, Any]] = []
    remaining = MAX_INLINE_ATTACHMENT_BYTES
    for attachment in attachments:
        size = int(attachment["size"])
        content_type = attachment["content_type"].lower()
        suffix = "." + attachment["filename"].lower().rsplit(".", 1)[-1]
        is_image = content_type in IMAGE_FORMATS and size <= INLINE_IMAGE_BYTES
        is_document = suffix in DOCUMENT_FORMATS and size <= INLINE_DOCUMENT_BYTES
        if (not is_image and not is_document) or size > remaining:
            continue
        body = s3.get_object(Bucket=bucket, Key=attachment["s3_key"])["Body"].read()
        if len(body) != size:
            raise RuntimeError(f"attachment byte count changed: {attachment['filename']}")
        source = {"bytes": body}
        if is_image:
            blocks.append({"image": {"format": IMAGE_FORMATS[content_type], "source": source}})
        else:
            blocks.append(
                {
                    "document": {
                        "format": DOCUMENT_FORMATS[suffix],
                        "name": _document_name(attachment["filename"]),
                        "source": source,
                    }
                }
            )
        remaining -= size
    return blocks


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


def _run_tool(
    lambda_client: Any,
    function_name: str,
    name: str,
    inputs: Any,
    *,
    conversation_id: str,
    attachments: list[dict[str, Any]] | None = None,
) -> Any:
    if not isinstance(inputs, dict):
        raise ValueError("tool input must be an object")
    if name == "execute_task":
        objective = inputs.get("objective")
        if not isinstance(objective, str) or not objective.strip():
            raise ValueError("execute_task requires a non-empty objective")
        return _invoke_control(
            lambda_client,
            function_name,
            "POST",
            "/jobs",
            {
                "idea": objective,
                "task_type": "general_aws",
                "conversation_id": conversation_id,
                "attachments": attachments or [],
            },
        )
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
    attachments: list[dict[str, Any]] | None = None,
    s3: Any = None,
    attachments_bucket: str = "",
) -> dict[str, Any]:
    messages = _load_messages(table, conversation_id)
    if attachments:
        if s3 is None or not attachments_bucket:
            raise RuntimeError("attachment storage is not configured")
        messages[-1]["content"].extend(
            _model_attachment_blocks(s3, attachments_bucket, attachments)
        )
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
                    conversation_id=conversation_id,
                    attachments=attachments,
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
    s3: Any = None,
    attachments_bucket: str = "",
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

        if (
            len(parts) == 3
            and parts[0] == "conversations"
            and parts[2] == "attachments"
            and method == "POST"
        ):
            if s3 is None or not attachments_bucket:
                raise RuntimeError("attachment storage is not configured")
            conversation_id = parts[1]
            _get_meta(table, conversation_id, owner_id)
            filename = _safe_filename(body.get("filename"))
            content_type = body.get("content_type") or "application/octet-stream"
            if not isinstance(content_type, str) or len(content_type) > 200:
                raise RequestError(400, "content_type is invalid")
            size = body.get("size")
            if not isinstance(size, int) or isinstance(size, bool) or not 1 <= size <= MAX_UPLOAD_BYTES:
                raise RequestError(400, "file size is outside Igor's upload range")
            attachment_id = uuid.uuid4().hex
            key = _attachment_key(owner_id, conversation_id, attachment_id, filename)
            created = s3.create_multipart_upload(
                Bucket=attachments_bucket,
                Key=key,
                ContentType=content_type,
                ServerSideEncryption="AES256",
                Metadata={
                    "igor-owner": owner_id,
                    "igor-conversation": conversation_id,
                    "igor-attachment": attachment_id,
                },
            )
            part_size = _part_size(size)
            part_count = (size + part_size - 1) // part_size
            timestamp = now_iso()
            table.put_item(
                Item={
                    "conversation_id": conversation_id,
                    "record_key": f"ATTACH#{attachment_id}",
                    "attachment_id": attachment_id,
                    "owner_id": owner_id,
                    "filename": filename,
                    "content_type": content_type,
                    "size": size,
                    "s3_key": key,
                    "s3_uri": f"s3://{attachments_bucket}/{key}",
                    "upload_id": created["UploadId"],
                    "part_size": part_size,
                    "part_count": part_count,
                    "status": "UPLOADING",
                    "created_at": timestamp,
                    "updated_at": timestamp,
                },
                ConditionExpression="attribute_not_exists(record_key)",
            )
            return response(
                201,
                {
                    "attachment_id": attachment_id,
                    "filename": filename,
                    "part_size": part_size,
                    "part_count": part_count,
                    "status": "UPLOADING",
                },
            )

        if (
            len(parts) == 5
            and parts[0] == "conversations"
            and parts[2] == "attachments"
            and parts[4] == "part-url"
            and method == "POST"
        ):
            if s3 is None or not attachments_bucket:
                raise RuntimeError("attachment storage is not configured")
            conversation_id, attachment_id = parts[1], parts[3]
            _get_meta(table, conversation_id, owner_id)
            attachment = _get_attachment(table, conversation_id, attachment_id)
            if attachment.get("owner_id") != owner_id or attachment.get("status") != "UPLOADING":
                raise RequestError(409, "attachment is not accepting parts")
            part_number = body.get("part_number")
            if (
                not isinstance(part_number, int)
                or isinstance(part_number, bool)
                or not 1 <= part_number <= int(attachment["part_count"])
            ):
                raise RequestError(400, "part_number is invalid")
            url = s3.generate_presigned_url(
                "upload_part",
                Params={
                    "Bucket": attachments_bucket,
                    "Key": attachment["s3_key"],
                    "UploadId": attachment["upload_id"],
                    "PartNumber": part_number,
                },
                ExpiresIn=3600,
            )
            return response(200, {"url": url, "part_number": part_number})

        if (
            len(parts) == 5
            and parts[0] == "conversations"
            and parts[2] == "attachments"
            and parts[4] == "complete"
            and method == "POST"
        ):
            if s3 is None or not attachments_bucket:
                raise RuntimeError("attachment storage is not configured")
            conversation_id, attachment_id = parts[1], parts[3]
            _get_meta(table, conversation_id, owner_id)
            attachment = _get_attachment(table, conversation_id, attachment_id)
            if attachment.get("owner_id") != owner_id or attachment.get("status") != "UPLOADING":
                raise RequestError(409, "attachment is not awaiting completion")
            parts_value = body.get("parts")
            expected = int(attachment["part_count"])
            if not isinstance(parts_value, list) or len(parts_value) != expected:
                raise RequestError(400, f"completion requires exactly {expected} uploaded parts")
            completed_parts: list[dict[str, Any]] = []
            for index, part in enumerate(parts_value, 1):
                if not isinstance(part, dict) or part.get("part_number") != index:
                    raise RequestError(400, "uploaded parts must be complete and ordered")
                etag = part.get("etag")
                if not isinstance(etag, str) or not etag:
                    raise RequestError(400, "every uploaded part requires an ETag")
                completed_parts.append({"PartNumber": index, "ETag": etag})
            s3.complete_multipart_upload(
                Bucket=attachments_bucket,
                Key=attachment["s3_key"],
                UploadId=attachment["upload_id"],
                MultipartUpload={"Parts": completed_parts},
            )
            head = s3.head_object(Bucket=attachments_bucket, Key=attachment["s3_key"])
            actual_size = int(head["ContentLength"])
            if actual_size != int(attachment["size"]):
                s3.delete_object(Bucket=attachments_bucket, Key=attachment["s3_key"])
                table.update_item(
                    Key={"conversation_id": conversation_id, "record_key": f"ATTACH#{attachment_id}"},
                    UpdateExpression="SET #status = :failed, updated_at = :updated, failure = :failure",
                    ExpressionAttributeNames={"#status": "status"},
                    ExpressionAttributeValues={
                        ":failed": "FAILED",
                        ":updated": now_iso(),
                        ":failure": "uploaded byte count did not match the selected file",
                    },
                )
                raise RequestError(400, "uploaded byte count did not match the selected file")
            table.update_item(
                Key={"conversation_id": conversation_id, "record_key": f"ATTACH#{attachment_id}"},
                UpdateExpression="SET #status = :ready, updated_at = :updated REMOVE upload_id",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={":ready": "READY", ":updated": now_iso()},
            )
            return response(
                200,
                {
                    "attachment_id": attachment_id,
                    "filename": attachment["filename"],
                    "content_type": attachment["content_type"],
                    "size": actual_size,
                    "status": "READY",
                },
            )

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
            text = body.get("message", "")
            if not isinstance(text, str):
                raise RequestError(400, "message must be a string")
            text = text.strip()
            if len(text) > MAX_MESSAGE_LENGTH:
                raise RequestError(400, f"message exceeds {MAX_MESSAGE_LENGTH} characters")
            attachments = _ready_attachments(table, conversation_id, body.get("attachment_ids"))
            if not text and not attachments:
                raise RequestError(400, "message or attachment is required")
            if not text:
                text = "Inspect the attached file or files."

            _put_message(
                table,
                conversation_id=conversation_id,
                role="user",
                content=_attachment_content(text, attachments),
                display_text=text,
                attachments=attachments,
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
                attachments=attachments,
                s3=s3,
                attachments_bucket=attachments_bucket,
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
        s3=boto3.client("s3"),
        attachments_bucket=os.environ["ATTACHMENTS_BUCKET"],
    )
