"""Public shell for Igor's private, Cognito-authenticated dashboard."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


def _response(status_code: int, content_type: str, body: str) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {
            "content-type": content_type,
            "cache-control": "no-store",
            "x-content-type-options": "nosniff",
            "x-frame-options": "DENY",
            "referrer-policy": "no-referrer",
        },
        "body": body,
    }


def render_dashboard(*, api_url: str, client_id: str, region: str) -> dict[str, Any]:
    config = {"apiUrl": api_url.rstrip("/"), "clientId": client_id, "region": region}
    template = Path(__file__).with_name("index.html").read_text(encoding="utf-8")
    body = template.replace("__IGOR_CONFIG__", json.dumps(config, separators=(",", ":")))
    result = _response(200, "text/html; charset=utf-8", body)

    api_origin = f"{urlsplit(api_url).scheme}://{urlsplit(api_url).netloc}"
    cognito_origin = f"https://cognito-idp.{region}.amazonaws.com"
    result["headers"]["content-security-policy"] = (
        "default-src 'none'; "
        "base-uri 'none'; "
        f"connect-src {api_origin} {cognito_origin}; "
        "form-action 'self'; frame-ancestors 'none'; "
        "script-src 'unsafe-inline'; style-src 'unsafe-inline'"
    )
    return result


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    del context
    path = event.get("rawPath") or event.get("path") or "/"
    if path.rstrip("/") not in ("", "/"):
        return _response(404, "application/json", '{"error":"not found"}')
    return render_dashboard(
        api_url=os.environ["DASHBOARD_API_URL"],
        client_id=os.environ["COGNITO_CLIENT_ID"],
        region=os.environ["COGNITO_REGION"],
    )
