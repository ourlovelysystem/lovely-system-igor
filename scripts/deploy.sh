#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
cd "$repo_root"

stack_name="${IGOR_STACK_NAME:-igor}"
region="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
model_id="${IGOR_MODEL_ID:-global.openai.gpt-5.6-terra}"
source_repository="${IGOR_SOURCE_REPOSITORY:-https://github.com/ourlovelysystem/lovely-system-igor.git}"
source_revision="${IGOR_SOURCE_REVISION:-$(git rev-parse HEAD 2>/dev/null || echo main)}"

# Validate the required clients before any stack lookup.  This prevents a missing
# AWS CLI from being misreported as a nonexistent stack (and accidentally taking
# the new-stack credential path).
command -v aws >/dev/null || { echo "AWS CLI is required" >&2; exit 1; }
command -v sam >/dev/null || { echo "AWS SAM CLI is required" >&2; exit 1; }

github_token_secret_name=""
github_token_parameter=()

# An omitted credential setting must not clear an existing integration.  Read only
# the Secrets Manager *name* from CloudFormation; never retrieve the secret.
if [[ -v IGOR_GITHUB_TOKEN_SECRET_NAME ]]; then
  github_token_secret_name="$IGOR_GITHUB_TOKEN_SECRET_NAME"
  github_token_parameter=("GitHubTokenSecretName=$github_token_secret_name")
else
  existing_stack_id=""
  if ! existing_stack_id="$(aws cloudformation describe-stacks \
    --stack-name "$stack_name" \
    --region "$region" \
    --query 'Stacks[0].StackId' \
    --output text 2>/tmp/igor-deploy-stack-lookup.err)"; then
    lookup_error="$(cat /tmp/igor-deploy-stack-lookup.err)"
    rm -f /tmp/igor-deploy-stack-lookup.err
    if grep -Eqi "does not exist|doesn't exist" <<<"$lookup_error"; then
      existing_stack_id=""
    else
      echo "Unable to determine whether stack $stack_name exists; refusing to deploy." >&2
      exit 1
    fi
  else
    rm -f /tmp/igor-deploy-stack-lookup.err
  fi

  if [[ -n "$existing_stack_id" && "$existing_stack_id" != "None" ]]; then
    if ! github_token_secret_name="$(aws cloudformation describe-stacks \
      --stack-name "$stack_name" \
      --region "$region" \
      --query 'Stacks[0].Parameters[?ParameterKey==`GitHubTokenSecretName`].ParameterValue | [0]' \
      --output text)"; then
      echo "Unable to read the existing GitHubTokenSecretName parameter; refusing to deploy." >&2
      exit 1
    fi
    # CloudFormation renders an empty String parameter as either an empty string or
    # `None` in text output. Both are readable, valid no-credential settings.
    # Pass an explicit empty override so SAM preserves that configuration rather
    # than inventing a credential or applying a different default.
    if [[ "$github_token_secret_name" == "None" ]]; then
      github_token_secret_name=""
    fi
    github_token_parameter=("GitHubTokenSecretName=$github_token_secret_name")
  fi
fi

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
    "SourceRevision=$source_revision" \
    "${github_token_parameter[@]}"

igor_url="$(aws cloudformation describe-stacks \
  --stack-name "$stack_name" \
  --region "$region" \
  --query 'Stacks[0].Outputs[?OutputKey==`IgorUrl`].OutputValue' \
  --output text)"

dashboard_url="$(aws cloudformation describe-stacks \
  --stack-name "$stack_name" \
  --region "$region" \
  --query 'Stacks[0].Outputs[?OutputKey==`DashboardUrl`].OutputValue' \
  --output text)"

echo "Igor deployed: $igor_url"
echo "Igor dashboard: $dashboard_url"

if [[ -n "${IGOR_OPERATOR_EMAIL:-}" ]]; then
  "$script_dir/create-operator.sh" "$IGOR_OPERATOR_EMAIL"
else
  echo "Create a dashboard operator: ./scripts/create-operator.sh you@example.com"
fi
