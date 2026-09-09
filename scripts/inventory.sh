#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
stack_name="${IGOR_STACK_NAME:-igor}"
region="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
output="${1:-$script_dir/../igor-retirement-inventory.json}"
reference_stack="${IGOR_REFERENCE_STACK_NAME:-AmazonChimeSDKMediaStreams}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

command -v aws >/dev/null || { echo "AWS CLI is required" >&2; exit 1; }
command -v python3 >/dev/null || { echo "Python 3 is required" >&2; exit 1; }

aws cloudformation describe-stacks \
  --stack-name "$stack_name" --region "$region" --output json --no-cli-pager \
  > "$work/stack.json"
aws cloudformation list-stack-resources \
  --stack-name "$stack_name" --region "$region" --output json --no-cli-pager \
  > "$work/resources.json"

if ! aws cloudformation describe-stacks \
  --stack-name "$reference_stack" --region "$region" --output json --no-cli-pager \
  > "$work/reference.json" 2> "$work/reference.err"; then
  printf '{"Stacks":[]}' > "$work/reference.json"
fi

python3 - "$work/stack.json" "$work/resources.json" "$work/reference.json" "$output" "$region" <<'PY'
import datetime
import json
import pathlib
import sys

stack_doc = json.load(open(sys.argv[1]))
resource_doc = json.load(open(sys.argv[2]))
reference_doc = json.load(open(sys.argv[3]))
stack = stack_doc["Stacks"][0]
parameters = {item["ParameterKey"]: item.get("ParameterValue", "") for item in stack.get("Parameters", [])}
outputs = {item["OutputKey"]: item.get("OutputValue", "") for item in stack.get("Outputs", [])}
resources = [
    {
        "logical_id": item.get("LogicalResourceId"),
        "physical_id": item.get("PhysicalResourceId"),
        "type": item.get("ResourceType"),
        "status": item.get("ResourceStatus"),
    }
    for item in resource_doc.get("StackResourceSummaries", [])
]
reference = None
if reference_doc.get("Stacks"):
    raw = reference_doc["Stacks"][0]
    reference = {
        "stack_name": raw.get("StackName"),
        "stack_id": raw.get("StackId"),
        "status": raw.get("StackStatus"),
        "parameters": {item["ParameterKey"]: item.get("ParameterValue", "") for item in raw.get("Parameters", [])},
    }
manifest = {
    "schema_version": 1,
    "captured_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "region": sys.argv[5],
    "igor": {
        "stack_name": stack.get("StackName"),
        "stack_id": stack.get("StackId"),
        "status": stack.get("StackStatus"),
        "source_repository": parameters.get("SourceRepository"),
        "source_revision": parameters.get("SourceRevision"),
        "parameters": parameters,
        "outputs": outputs,
        "resources": resources,
    },
    "reference_media_stack": reference,
    "retention": {
        "cloudformation_logical_ids": ["JobsTable", "ConversationsTable", "EvidenceBucket", "TelephoneCallsTable", "OperatorPool"],
        "external_secrets_are_not_deleted": True,
        "igor_created_workloads_are_not_deleted": True,
        "telephone_numbers_are_not_released": True,
    },
}
destination = pathlib.Path(sys.argv[4])
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
print(destination)
PY
