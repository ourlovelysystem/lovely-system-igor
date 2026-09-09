#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/bin" "$work/run"

cat > "$work/bin/aws" <<'AWS'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$AWS_LOG"
case "$*" in
  *'cloudformation describe-stacks --stack-name igor'*)
    cat <<JSON
{"Stacks":[{"StackName":"igor","StackId":"arn:igor","StackStatus":"UPDATE_COMPLETE","Parameters":[{"ParameterKey":"SourceRepository","ParameterValue":"https://github.com/ourlovelysystem/lovely-system-igor.git"},{"ParameterKey":"SourceRevision","ParameterValue":"abc123"}],"Outputs":[{"OutputKey":"WorkerProjectName","OutputValue":"igor-worker"},{"OutputKey":"EvidenceBucketName","OutputValue":"igor-evidence"}]}]}
JSON
    ;;
  *'cloudformation describe-stacks --stack-name AmazonChimeSDKMediaStreams'*)
    route="${REFERENCE_ROUTE:-bedrock}"
    ingress="${REFERENCE_INGRESS:-reference}"
    printf '{"Stacks":[{"StackName":"AmazonChimeSDKMediaStreams","StackId":"arn:reference","StackStatus":"UPDATE_COMPLETE","Parameters":[{"ParameterKey":"ResponseRouteParameter","ParameterValue":"%s"},{"ParameterKey":"IngressHandlerParameter","ParameterValue":"%s"}]}]}\n' "$route" "$ingress"
    ;;
  *'cloudformation list-stack-resources'*)
    printf '%s\n' '{"StackResourceSummaries":[{"LogicalResourceId":"DiagnosticAudioBucket","PhysicalResourceId":"igor-diagnostic","ResourceType":"AWS::S3::Bucket","ResourceStatus":"CREATE_COMPLETE"},{"LogicalResourceId":"EvidenceBucket","PhysicalResourceId":"igor-evidence","ResourceType":"AWS::S3::Bucket","ResourceStatus":"CREATE_COMPLETE"}]}'
    ;;
  *'codebuild list-builds-for-project'*)
    printf '%s\n' '{"ids":["igor-worker:1"]}'
    ;;
  *'codebuild batch-get-builds'*)
    printf '{"builds":[{"id":"igor-worker:1","buildStatus":"%s"}]}\n' "${BUILD_STATUS:-SUCCEEDED}"
    ;;
  *'s3 cp'*) ;;
  *'s3 rm'*) ;;
  *'cloudformation delete-stack'*) ;;
  *'cloudformation wait stack-delete-complete'*) ;;
  *) echo "unexpected aws command: $*" >&2; exit 99 ;;
esac
AWS
chmod +x "$work/bin/aws"

run_retire() {
  env PATH="$work/bin:$PATH" AWS_LOG="$work/aws.log" REFERENCE_ROUTE="${REFERENCE_ROUTE:-bedrock}" REFERENCE_INGRESS="${REFERENCE_INGRESS:-reference}" BUILD_STATUS="${BUILD_STATUS:-SUCCEEDED}" bash "$repo_root/scripts/retire.sh" "$@"
}

cd "$work/run"
: > "$work/aws.log"
run_retire > "$work/out"
grep -q 'Retirement gates passed' "$work/out"
grep -q 'Dry run only' "$work/out"
! grep -a -q 'delete-stack' "$work/aws.log"
! grep -a -q 's3 rm' "$work/aws.log"

: > "$work/aws.log"
if REFERENCE_ROUTE=igor_bridge run_retire > "$work/out" 2> "$work/err"; then
  echo 'expected Igor reference route to block retirement' >&2
  exit 1
fi
grep -q 'still routes to Igor' "$work/err"
! grep -a -q 'delete-stack' "$work/aws.log"

: > "$work/aws.log"
if BUILD_STATUS=IN_PROGRESS run_retire > "$work/out" 2> "$work/err"; then
  echo 'expected active build to block retirement' >&2
  exit 1
fi
grep -q 'Active Igor CodeBuild executions remain' "$work/err"
! grep -a -q 'delete-stack' "$work/aws.log"

: > "$work/aws.log"
if run_retire --execute > "$work/out" 2> "$work/err"; then
  echo 'expected missing confirmation to block execution' >&2
  exit 1
fi
grep -q 'Set IGOR_RETIRE_CONFIRM=igor' "$work/err"
! grep -a -q 'delete-stack' "$work/aws.log"

: > "$work/aws.log"
IGOR_RETIRE_CONFIRM=igor run_retire --execute > "$work/out"
grep -a -q 's3 cp' "$work/aws.log"
grep -a -q 's3 rm' "$work/aws.log"
grep -a -q 'cloudformation.*delete-stack' "$work/aws.log"
grep -a -q 'cloudformation.*wait.*stack-delete-complete' "$work/aws.log"
grep -q 'Deleted CloudFormation stack: igor' "$work/out"

echo 'retire.sh regression tests passed'
