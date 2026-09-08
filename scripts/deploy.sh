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
if [[ -n "${IGOR_GITHUB_TOKEN_SECRET_NAME+x}" ]]; then
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

# The reference-compatible voice role is scoped to the exact existing PIN secret
# ARN. Resolve metadata only; do not read, rotate, copy, or print its value.
telephone_auth_secret_name="${IGOR_TELEPHONE_AUTH_SECRET_NAME:-}"
if [[ -z "$telephone_auth_secret_name" ]]; then
  telephone_auth_secret_name="$(aws cloudformation describe-stacks \
    --stack-name "$stack_name" --region "$region" \
    --query 'Stacks[0].Parameters[?ParameterKey==`TelephoneAuthSecretName`].ParameterValue | [0]' --output text)"
fi
[[ "$telephone_auth_secret_name" != "None" && -n "$telephone_auth_secret_name" ]] || { echo "TelephoneAuthSecretName is required; refusing to deploy." >&2; exit 1; }
telephone_auth_secret_arn="${IGOR_TELEPHONE_AUTH_SECRET_ARN:-}"
if [[ -z "$telephone_auth_secret_arn" ]]; then
  telephone_auth_secret_arn="$(aws secretsmanager describe-secret --secret-id "$telephone_auth_secret_name" --region "$region" --query ARN --output text)"
fi
[[ "$telephone_auth_secret_arn" != "None" && -n "$telephone_auth_secret_arn" ]] || { echo "TelephoneAuthSecretArn is required; refusing to deploy." >&2; exit 1; }

# Preserve an existing binding when present. During the first binding, discover
# the reference stack's existing meeting table by resource type and logical ID;
# this reads infrastructure metadata only.
valid_table_name() {
  [[ "$1" =~ ^[A-Za-z0-9_.-]+$ && ${#1} -ge 3 && ${#1} -le 255 ]]
}
reference_meeting_table_name="${IGOR_REFERENCE_MEETING_TABLE_NAME:-}"
if [[ -z "$reference_meeting_table_name" && -n "${existing_stack_id:-}" ]]; then
  reference_meeting_table_name="$(aws cloudformation describe-stacks \
    --stack-name "$stack_name" --region "$region" \
    --query 'Stacks[0].Parameters[?ParameterKey==`ReferenceMeetingTableName`].ParameterValue | [0]' --output text)"
  valid_table_name "$reference_meeting_table_name" || reference_meeting_table_name=""
fi
if [[ -z "$reference_meeting_table_name" ]]; then
  reference_stack_name="${IGOR_REFERENCE_STACK_NAME:-AmazonChimeSDKMediaStreams}"
  reference_meeting_table_name="$(aws cloudformation list-stack-resources \
    --stack-name "$reference_stack_name" --region "$region" \
    --no-paginate \
    --query 'StackResourceSummaries[?ResourceType==`AWS::DynamoDB::Table` && contains(LogicalResourceId, `meetingTable`)].PhysicalResourceId | [0]' --output text)"
fi
valid_table_name "$reference_meeting_table_name" || { echo "ReferenceMeetingTableName must be one exact DynamoDB table name; refusing to deploy." >&2; exit 1; }

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
    "TelephoneAuthSecretName=$telephone_auth_secret_name" \
    "TelephoneAuthSecretArn=$telephone_auth_secret_arn" \
    "ReferenceMeetingTableName=$reference_meeting_table_name" \
    "${github_token_parameter[@]}"

# The bounded diagnostic WAV is uploaded only after CloudFormation creates its private bucket and Chime policy.
audio_bucket="$(aws cloudformation describe-stack-resource --stack-name "$stack_name" --logical-resource-id DiagnosticAudioBucket --region "$region" --query 'StackResourceDetail.PhysicalResourceId' --output text)"
# Generate unmistakable spoken content, rather than a format-valid tone. Polly PCM is
# raw signed 16-bit mono little-endian; wrap it in the WAV required by PlayAudio.
aws polly synthesize-speech --region "$region" --engine standard --voice-id Joanna \
  --output-format pcm --sample-rate 8000 --text "Hello from Igor" /tmp/igor-018-diagnostic.pcm
python3 - <<'PY_WAV'
import wave
with open("/tmp/igor-018-diagnostic.pcm", "rb") as source, wave.open("/tmp/igor-018-diagnostic.wav", "wb") as output:
    output.setnchannels(1)
    output.setsampwidth(2)
    output.setframerate(8000)
    output.writeframes(source.read())
PY_WAV
aws s3 cp /tmp/igor-018-diagnostic.wav "s3://$audio_bucket/igor-018/diagnostic.wav" --region "$region" --sse AES256 --content-type audio/wav

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
