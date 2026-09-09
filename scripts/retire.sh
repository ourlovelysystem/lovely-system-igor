#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
stack_name="${IGOR_STACK_NAME:-igor}"
region="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
reference_stack="${IGOR_REFERENCE_STACK_NAME:-AmazonChimeSDKMediaStreams}"
execute=false

usage() {
  cat <<'EOF'
Usage: ./scripts/retire.sh [--execute]

Without --execute, writes a read-only retirement inventory and checks all gates.
With --execute, requires IGOR_RETIRE_CONFIRM to equal the exact stack name, archives
the manifest in Igor's retained evidence bucket, removes the disposable diagnostic
audio, and deletes only the Igor CloudFormation stack.

The script never deletes retained tables, the evidence bucket, the Cognito user
pool, external secrets, telephone numbers, the reference media stack, or workloads
created by Igor jobs.
EOF
}

case "${1:-}" in
  "") ;;
  --execute) execute=true ;;
  -h|--help) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac

command -v aws >/dev/null || { echo "AWS CLI is required" >&2; exit 1; }
command -v python3 >/dev/null || { echo "Python 3 is required" >&2; exit 1; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
manifest="$work/igor-retirement-inventory.json"
"$script_dir/inventory.sh" "$manifest" >/dev/null

python3 - "$manifest" "$reference_stack" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1]))
stack = manifest["igor"]
if stack["status"].endswith("_IN_PROGRESS"):
    raise SystemExit(f'Igor stack is busy ({stack["status"]}); refusing retirement')
reference = manifest.get("reference_media_stack")
if not reference:
    raise SystemExit(f'Reference stack {sys.argv[2]} is unavailable; refusing to orphan its Igor integration')
parameters = reference.get("parameters", {})
selected = {key: value for key, value in parameters.items() if "ingresshandler" in key.lower() or "responseroute" in key.lower()}
unsafe = {key: value for key, value in selected.items() if "igor" in str(value).lower()}
if unsafe:
    rendered = ", ".join(f"{key}={value}" for key, value in sorted(unsafe.items()))
    raise SystemExit("Reference media stack still routes to Igor (" + rendered + "). Restore its standalone reference/bedrock route before retiring Igor.")
if not selected:
    raise SystemExit("Reference media routing parameters were not found; refusing an unverified retirement")
PY

worker_project="$(python3 - "$manifest" <<'PY'
import json, sys
print(json.load(open(sys.argv[1]))["igor"]["outputs"].get("WorkerProjectName", ""))
PY
)"
[[ -n "$worker_project" ]] || { echo "WorkerProjectName output is missing; refusing retirement" >&2; exit 1; }
aws codebuild list-builds-for-project --project-name "$worker_project" --region "$region" --sort-order DESC --max-items 25 --output json --no-cli-pager > "$work/builds.json"
python3 - "$work/builds.json" > "$work/build-ids.txt" <<'PY'
import json, sys
for build_id in json.load(open(sys.argv[1])).get("ids", []):
    print(build_id)
PY
if [[ -s "$work/build-ids.txt" ]]; then
  build_ids=()
  while IFS= read -r build_id; do
    build_ids+=("$build_id")
  done < "$work/build-ids.txt"
  aws codebuild batch-get-builds --ids "${build_ids[@]}" --region "$region" --output json --no-cli-pager > "$work/build-details.json"
  python3 - "$work/build-details.json" <<'PY'
import json, sys
active = [build["id"] for build in json.load(open(sys.argv[1])).get("builds", []) if build.get("buildStatus") == "IN_PROGRESS"]
if active:
    raise SystemExit("Active Igor CodeBuild executions remain: " + ", ".join(active))
PY
fi

cp "$manifest" "$repo_root/igor-retirement-inventory.json"
echo "Retirement gates passed. Inventory: $repo_root/igor-retirement-inventory.json"
if [[ "$execute" != true ]]; then
  echo "Dry run only. Re-run with IGOR_RETIRE_CONFIRM=$stack_name and --execute to delete the Igor stack."
  exit 0
fi
[[ "${IGOR_RETIRE_CONFIRM:-}" == "$stack_name" ]] || { echo "Set IGOR_RETIRE_CONFIRM=$stack_name to authorize deletion of exactly that stack." >&2; exit 1; }

evidence_bucket="$(python3 - "$manifest" <<'PY'
import json, sys
print(json.load(open(sys.argv[1]))["igor"]["outputs"].get("EvidenceBucketName", ""))
PY
)"
[[ -n "$evidence_bucket" ]] || { echo "EvidenceBucketName output is missing; refusing retirement" >&2; exit 1; }
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
archive_key="retirement/$timestamp/igor-retirement-inventory.json"
aws s3 cp "$manifest" "s3://$evidence_bucket/$archive_key" --region "$region" --sse AES256 --no-progress

diagnostic_bucket="$(python3 - "$manifest" <<'PY'
import json, sys
for resource in json.load(open(sys.argv[1]))["igor"]["resources"]:
    if resource["logical_id"] == "DiagnosticAudioBucket":
        print(resource.get("physical_id") or "")
        break
PY
)"
if [[ -n "$diagnostic_bucket" ]]; then
  aws s3 rm "s3://$diagnostic_bucket" --recursive --region "$region" --no-progress
fi
aws cloudformation delete-stack --stack-name "$stack_name" --region "$region"
aws cloudformation wait stack-delete-complete --stack-name "$stack_name" --region "$region"
echo "Deleted CloudFormation stack: $stack_name"
echo "Retirement evidence retained at: s3://$evidence_bucket/$archive_key"
echo "Retained data resources are listed in: $repo_root/igor-retirement-inventory.json"
