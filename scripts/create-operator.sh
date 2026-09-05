#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 || "$1" != *@* ]]; then
  echo "Usage: $0 you@example.com" >&2
  exit 2
fi

operator_email="$1"
stack_name="${IGOR_STACK_NAME:-igor}"
region="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"

user_pool_id="$(aws cloudformation describe-stacks \
  --stack-name "$stack_name" \
  --region "$region" \
  --query 'Stacks[0].Outputs[?OutputKey==`OperatorUserPoolId`].OutputValue' \
  --output text)"

if aws cognito-idp admin-get-user \
  --user-pool-id "$user_pool_id" \
  --username "$operator_email" \
  --region "$region" >/dev/null 2>&1; then
  echo "Igor dashboard operator already exists: $operator_email"
  exit 0
fi

aws cognito-idp admin-create-user \
  --user-pool-id "$user_pool_id" \
  --username "$operator_email" \
  --user-attributes \
    "Name=email,Value=$operator_email" \
    "Name=email_verified,Value=true" \
  --desired-delivery-mediums EMAIL \
  --region "$region" >/dev/null

echo "Igor dashboard invitation sent to: $operator_email"
