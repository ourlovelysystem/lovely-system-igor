#!/usr/bin/env python3
"""Configure and serve Igor's GitHub token to Git without putting it in URLs."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any


HELPER_PATH = Path("/tmp/igor/scripts/github-credential.py")


def _token_from_response(response: dict[str, Any]) -> str:
    token = response.get("SecretString")
    if not isinstance(token, str) or not token.strip():
        raise RuntimeError("GitHub token secret is empty or is not a string")
    return token.strip()


def _load_token(secret_name: str) -> str:
    import boto3

    response = boto3.client("secretsmanager").get_secret_value(SecretId=secret_name)
    return _token_from_response(response)


def configure() -> int:
    if not os.environ.get("GITHUB_TOKEN_SECRET_NAME"):
        print("GitHub credentials are not configured; GitHub access remains read-only.")
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
    print("GitHub authentication configured for this worker.")
    return 0


def credential(operation: str) -> int:
    fields = dict(
        line.rstrip("\n").split("=", 1)
        for line in sys.stdin
        if "=" in line
    )
    if operation != "get" or fields.get("host") != "github.com":
        return 0
    secret_name = os.environ.get("GITHUB_TOKEN_SECRET_NAME")
    if not secret_name:
        return 0
    print("username=x-access-token")
    print(f"password={_load_token(secret_name)}")
    return 0


def main() -> int:
    operation = sys.argv[1] if len(sys.argv) > 1 else ""
    if operation == "configure":
        return configure()
    return credential(operation)


if __name__ == "__main__":
    raise SystemExit(main())
