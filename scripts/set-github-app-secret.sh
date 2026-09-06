#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 || $# -gt 4 ]]; then
  echo "Usage: $0 APP_ID INSTALLATION_ID PRIVATE_KEY_FILE [SECRET_NAME]" >&2
  exit 2
fi

app_id="$1"
installation_id="$2"
private_key_file="$3"
secret_name="${4:-igor/github-app}"
region="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"

command -v aws >/dev/null || { echo "AWS CLI is required" >&2; exit 1; }
command -v python3 >/dev/null || { echo "Python 3 is required" >&2; exit 1; }
[[ -s "$private_key_file" ]] || { echo "Private key file not found or empty" >&2; exit 1; }

secret_file="$(mktemp)"
trap 'rm -f "$secret_file"' EXIT

python3 - "$app_id" "$installation_id" "$private_key_file" "$secret_file" <<'PY'
import json
import pathlib
import sys

app_id, installation_id, private_key_path, output_path = sys.argv[1:]
payload = {
    "app_id": app_id,
    "installation_id": installation_id,
    "private_key": pathlib.Path(private_key_path).read_text(encoding="utf-8"),
}
pathlib.Path(output_path).write_text(json.dumps(payload), encoding="utf-8")
PY

if aws secretsmanager describe-secret --secret-id "$secret_name" --region "$region" >/dev/null 2>&1; then
  aws secretsmanager put-secret-value \
    --secret-id "$secret_name" \
    --region "$region" \
    --secret-string "file://$secret_file" \
    --query ARN \
    --output text
else
  aws secretsmanager create-secret \
    --name "$secret_name" \
    --region "$region" \
    --description "GitHub App identity used by Igor workers" \
    --secret-string "file://$secret_file" \
    --query ARN \
    --output text
fi

echo "GitHub App credential stored. Deploy Igor with:"
echo "IGOR_GITHUB_APP_SECRET_NAME=$secret_name ./scripts/deploy.sh"
