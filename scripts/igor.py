#!/usr/bin/env python3
"""Submit and inspect Igor jobs through an IAM-authenticated Function URL."""

from __future__ import annotations

import argparse
import json
import os
import urllib.request


def signed_request(url: str, method: str, body: dict | None, region: str) -> dict:
    try:
        import boto3
        from botocore.auth import SigV4Auth
        from botocore.awsrequest import AWSRequest
    except ImportError as exc:
        raise SystemExit("Install boto3 first: python3 -m pip install boto3") from exc

    payload = b"" if body is None else json.dumps(body).encode("utf-8")
    headers = {"content-type": "application/json"}
    credentials = boto3.Session().get_credentials()
    if credentials is None:
        raise SystemExit("No AWS credentials found")
    aws_request = AWSRequest(method=method, url=url, data=payload, headers=headers)
    SigV4Auth(credentials.get_frozen_credentials(), "lambda", region).add_auth(aws_request)
    request = urllib.request.Request(
        url,
        method=method,
        data=payload if body is not None else None,
        headers=dict(aws_request.headers.items()),
    )
    with urllib.request.urlopen(request, timeout=30) as result:
        return json.loads(result.read())


def main() -> None:
    parser = argparse.ArgumentParser(prog="igor")
    parser.add_argument("--url", default=os.environ.get("IGOR_URL"), required=False)
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    subparsers = parser.add_subparsers(dest="command", required=True)

    submit = subparsers.add_parser("submit")
    submit.add_argument("idea")
    submit.add_argument("--model-id")

    status = subparsers.add_parser("status")
    status.add_argument("job_id")
    args = parser.parse_args()
    if not args.url:
        parser.error("--url or IGOR_URL is required")
    base_url = args.url.rstrip("/")

    if args.command == "submit":
        body = {"idea": args.idea}
        if args.model_id:
            body["model_id"] = args.model_id
        result = signed_request(f"{base_url}/jobs", "POST", body, args.region)
    else:
        result = signed_request(f"{base_url}/jobs/{args.job_id}", "GET", None, args.region)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

