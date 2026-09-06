"""Igor's general task control API.

The same handler sits behind an IAM-authenticated Function URL for CLI use and
a Cognito-authenticated HTTP API for the operator dashboard.
"""

from __future__ import annotations

import base64
import json
import os
import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any


TERMINAL_STATES = {"WORKING", "FAILED", "BLOCKED", "INCOMPLETE"}
MAX_IDEA_LENGTH = 10_000
MAX_LISTED_JOBS = 100


def work_event(event_type: str, message: str, **fields: Any) -> dict[str, Any]:
    """Create an operator-safe event; never put command text or output here."""
    return {"at": now_iso(), "type": event_type, "message": message, **fields}


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
    context = event.get("requestContext", {})
    http = context.get("http", {})
    method = (http.get("method") or event.get("httpMethod") or "").upper()
    path = event.get("rawPath") or event.get("path") or "/"
    raw_body = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw_body = base64.b64decode(raw_body).decode("utf-8")
    try:
        body = json.loads(raw_body)
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError) as exc:
        raise ValueError("request body must be valid JSON") from exc
    if not isinstance(body, dict):
        raise ValueError("request body must be a JSON object")
    return method, path.rstrip("/") or "/", body


def _list_jobs(table: Any) -> list[dict[str, Any]]:
    """Return the newest jobs from this intentionally small pilot table."""
    items: list[dict[str, Any]] = []
    start_key: dict[str, Any] | None = None

    while len(items) < MAX_LISTED_JOBS:
        request: dict[str, Any] = {"Limit": MAX_LISTED_JOBS - len(items)}
        if start_key:
            request["ExclusiveStartKey"] = start_key
        page = table.scan(**request)
        items.extend(page.get("Items", []))
        start_key = page.get("LastEvaluatedKey")
        if not start_key:
            break

    items.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return items[:MAX_LISTED_JOBS]


def handle(
    event: dict[str, Any],
    *,
    table: Any,
    codebuild: Any,
    project_name: str,
    default_model_id: str,
) -> dict[str, Any]:
    try:
        method, path, body = _request(event)
    except ValueError as exc:
        return response(400, {"error": str(exc)})

    if method == "POST" and path == "/jobs":
        idea = body.get("idea")
        if not isinstance(idea, str) or not idea.strip():
            return response(400, {"error": "idea must be a non-empty string"})
        idea = idea.strip()
        if len(idea) > MAX_IDEA_LENGTH:
            return response(400, {"error": f"idea exceeds {MAX_IDEA_LENGTH} characters"})

        model_id = body.get("model_id", default_model_id)
        if not isinstance(model_id, str) or not model_id.strip():
            return response(400, {"error": "model_id must be a non-empty string"})

        recovery_source_job_id = body.get("recovery_source_job_id")
        if recovery_source_job_id is not None and (not isinstance(recovery_source_job_id, str) or not re.fullmatch(r"[0-9a-f]{32}", recovery_source_job_id)):
            return response(400, {"error": "recovery_source_job_id must be a 32-character job ID"})

        attachments = body.get("attachments", [])
        if not isinstance(attachments, list) or len(attachments) > 20:
            return response(400, {"error": "attachments must contain at most 20 items"})
        for attachment in attachments:
            if not isinstance(attachment, dict):
                return response(400, {"error": "every attachment must be an object"})
            s3_uri = attachment.get("s3_uri")
            if not isinstance(s3_uri, str) or not s3_uri.startswith("s3://"):
                return response(400, {"error": "every attachment requires an S3 URI"})

        job_id = uuid.uuid4().hex
        timestamp = now_iso()
        item = {
            "job_id": job_id,
            "task_type": "general_aws",
            "objective": idea,
            "idea": idea,
            "model_id": model_id.strip(),
            "status": "QUEUED",
            "stage": "queued",
            "progress_message": "Waiting for an execution worker.",
            "created_at": timestamp,
            "updated_at": timestamp,
            "current_activity": "Waiting for an execution worker.",
            "work_events": [work_event("queued", "Job queued; waiting for an execution worker.")],
        }
        if attachments:
            item["attachments"] = attachments
        if recovery_source_job_id:
            item["recovery_source_job_id"] = recovery_source_job_id
        conversation_id = body.get("conversation_id")
        if conversation_id is not None:
            if not isinstance(conversation_id, str) or not conversation_id.strip():
                return response(400, {"error": "conversation_id must be a non-empty string"})
            item["conversation_id"] = conversation_id.strip()
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(job_id)")
        try:
            build = codebuild.start_build(
                projectName=project_name,
                environmentVariablesOverride=[
                    {"name": "IGOR_JOB_ID", "value": job_id, "type": "PLAINTEXT"}
                ],
            )
        except Exception as exc:
            table.update_item(
                Key={"job_id": job_id},
                UpdateExpression="SET #s = :status, updated_at = :updated, failure = :failure, current_activity = :activity, work_events = list_append(if_not_exists(work_events, :empty), :events)",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":status": "FAILED",
                    ":updated": now_iso(),
                    ":failure": {"stage": "queue", "message": str(exc)[:1000]},
                    ":activity": "Unable to start the execution worker.",
                    ":empty": [],
                    ":events": [work_event("failure", "Unable to start the execution worker.", stage="queue")],
                },
            )
            return response(502, {"job_id": job_id, "status": "FAILED", "error": str(exc)})

        build_id = build.get("build", {}).get("id", "unknown")
        table.update_item(
            Key={"job_id": job_id},
            UpdateExpression="SET build_id = :build_id, updated_at = :updated, current_activity = :activity, work_events = list_append(if_not_exists(work_events, :empty), :events)",
            ExpressionAttributeValues={":build_id": build_id, ":updated": now_iso(), ":activity": "Execution worker accepted the job.", ":empty": [], ":events": [work_event("worker_started", "Execution worker accepted the job.")]},
        )
        return response(202, {"job_id": job_id, "status": "QUEUED", "build_id": build_id})

    if method == "GET" and path == "/jobs":
        return response(200, {"jobs": _list_jobs(table)})

    if method == "GET" and path.startswith("/jobs/"):
        job_id = path.removeprefix("/jobs/")
        if not job_id or "/" in job_id:
            return response(400, {"error": "invalid job id"})
        item = table.get_item(Key={"job_id": job_id}, ConsistentRead=True).get("Item")
        if not item:
            return response(404, {"error": "job not found", "job_id": job_id})
        return response(200, item)

    if method == "GET" and path == "/health":
        return response(200, {"name": "Igor", "status": "ready"})

    return response(404, {"error": "not found"})


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    del context
    import boto3

    table_name = os.environ["JOBS_TABLE"]
    return handle(
        event,
        table=boto3.resource("dynamodb").Table(table_name),
        codebuild=boto3.client("codebuild"),
        project_name=os.environ["WORKER_PROJECT"],
        default_model_id=os.environ["DEFAULT_MODEL_ID"],
    )
