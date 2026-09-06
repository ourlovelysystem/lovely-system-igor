#!/usr/bin/env bash
set -euo pipefail

secret_name="${1:-igor/github-token}"
region="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"

command -v aws >/dev/null || { echo "AWS CLI is required" >&2; exit 1; }

read -r -s -p "Paste Igor's GitHub token: " github_token
echo
[[ -n "$github_token" ]] || { echo "Token cannot be empty" >&2; exit 1; }

secret_file="$(mktemp)"
chmod 600 "$secret_file"
trap 'rm -f "$secret_file"' EXIT
printf '%s' "$github_token" > "$secret_file"
unset github_token

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
    --description "GitHub token used by Igor workers" \
    --secret-string "file://$secret_file" \
    --query ARN \
    --output text
fi

echo "GitHub token stored. Deploy Igor with:"
echo "IGOR_GITHUB_TOKEN_SECRET_NAME=$secret_name ./scripts/deploy.sh"
