#!/usr/bin/env python3
"""Configure and serve Git credentials for Igor's GitHub App installation."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any


HELPER_PATH = Path("/tmp/igor/scripts/github-app-credential.py")


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _github_jwt(app_id: str, private_key: str, *, now: int | None = None) -> str:
    issued_at = int(time.time() if now is None else now)
    header = _base64url(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _base64url(
        json.dumps(
            {"iat": issued_at - 60, "exp": issued_at + 540, "iss": str(app_id)},
            separators=(",", ":"),
        ).encode()
    )
    unsigned = f"{header}.{payload}".encode("ascii")
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=True) as key_file:
        key_file.write(private_key)
        key_file.flush()
        os.chmod(key_file.name, 0o600)
        signature = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", key_file.name],
            input=unsigned,
            check=True,
            capture_output=True,
        ).stdout
    return f"{unsigned.decode('ascii')}.{_base64url(signature)}"


def _load_secret(secret_name: str) -> dict[str, Any]:
    import boto3

    response = boto3.client("secretsmanager").get_secret_value(SecretId=secret_name)
    value = json.loads(response["SecretString"])
    required = {"app_id", "installation_id", "private_key"}
    if not isinstance(value, dict) or not required.issubset(value):
        raise RuntimeError(f"GitHub App secret must contain: {', '.join(sorted(required))}")
    return value


def _installation_token(secret: dict[str, Any]) -> str:
    jwt = _github_jwt(str(secret["app_id"]), str(secret["private_key"]))
    request = urllib.request.Request(
        f"https://api.github.com/app/installations/{secret['installation_id']}/access_tokens",
        data=b"{}",
        method="POST",
        headers={
            "accept": "application/vnd.github+json",
            "authorization": f"Bearer {jwt}",
            "content-type": "application/json",
            "user-agent": "igor-github-app",
            "x-github-api-version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.load(response)
    token = result.get("token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("GitHub did not return an installation token")
    return token


def configure() -> int:
    if not os.environ.get("GITHUB_APP_SECRET_NAME"):
        print("GitHub App credentials are not configured; GitHub access remains read-only.")
        return 0
    HELPER_PATH.chmod(0o700)
    subprocess.run(
        ["git", "config", "--global", "credential.helper", str(HELPER_PATH)],
        check=True,
    )
    subprocess.run(["git", "config", "--global", "credential.useHttpPath", "true"], check=True)
    subprocess.run(["git", "config", "--global", "user.name", "Igor"], check=True)
    subprocess.run(
        ["git", "config", "--global", "user.email", "igor@ourlovelysystem.org"],
        check=True,
    )
    print("GitHub App authentication configured for this worker.")
    return 0


def credential(operation: str) -> int:
    fields = dict(
        line.rstrip("\n").split("=", 1)
        for line in sys.stdin
        if "=" in line
    )
    if operation != "get" or fields.get("host") != "github.com":
        return 0
    secret_name = os.environ.get("GITHUB_APP_SECRET_NAME")
    if not secret_name:
        return 0
    token = _installation_token(_load_secret(secret_name))
    print("username=x-access-token")
    print(f"password={token}")
    return 0


def main() -> int:
    operation = sys.argv[1] if len(sys.argv) > 1 else ""
    if operation == "configure":
        return configure()
    return credential(operation)


if __name__ == "__main__":
    raise SystemExit(main())
