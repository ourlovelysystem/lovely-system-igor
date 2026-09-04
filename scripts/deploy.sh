#!/usr/bin/env bash
set -euo pipefail

stack_name="${IGOR_STACK_NAME:-igor}"
region="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
model_id="${IGOR_MODEL_ID:-global.openai.gpt-5.6-terra}"
source_repository="${IGOR_SOURCE_REPOSITORY:-https://github.com/ourlovelysystem/lovely-system-igor.git}"
source_revision="${IGOR_SOURCE_REVISION:-$(git rev-parse HEAD 2>/dev/null || echo main)}"

command -v aws >/dev/null || { echo "AWS CLI is required" >&2; exit 1; }
command -v sam >/dev/null || { echo "AWS SAM CLI is required" >&2; exit 1; }

sam build
sam deploy \
  --stack-name "$stack_name" \
  --region "$region" \
  --resolve-s3 \
  --capabilities CAPABILITY_IAM \
  --no-confirm-changeset \
  --no-fail-on-empty-changeset \
  --parameter-overrides \
    "DefaultModelId=$model_id" \
    "SourceRepository=$source_repository" \
    "SourceRevision=$source_revision"

igor_url="$(aws cloudformation describe-stacks \
  --stack-name "$stack_name" \
  --region "$region" \
  --query 'Stacks[0].Outputs[?OutputKey==`IgorUrl`].OutputValue' \
  --output text)"

echo "Igor deployed: $igor_url"
