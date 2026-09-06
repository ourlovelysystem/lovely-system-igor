#!/usr/bin/env bash
# Shell regression tests for scripts/deploy.sh. All AWS/SAM interactions are mocked.
set -euo pipefail
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/bin"
# Runtime-generated secret content: it must never reach output, command logs, or artifacts.
secret_sentinel="DEPLOY-SECRET-SENTINEL-$(date +%s%N)-$$"

cat > "$work/bin/sam" <<'SAM'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\0' "$@" >> "$SAM_LOG"
SAM
chmod +x "$work/bin/sam"
cat > "$work/bin/aws" <<'AWS'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\0' "$@" >> "$AWS_LOG"
# A deployment must never retrieve secret content. Record and reject any attempt.
if [[ "$*" == *'secretsmanager'* && "$*" == *'get-secret-value'* ]]; then
  printf '%s\n' 'secretsmanager get-secret-value' >> "$SECRET_RETRIEVAL_LOG"
  echo 'secret-value retrieval is forbidden' >&2
  exit 97
fi
if [[ "$*" == *'describe-stacks'* && "$*" == *'StackId'* ]]; then
  case "${SCENARIO:?}" in
    existing|existing-empty|existing-none|parameter-failure) printf 'stack-id\n' ;;
    new) echo 'An error occurred (ValidationError): Stack with id test-stack does not exist' >&2; exit 255 ;;
    stack-failure) echo 'lookup denied' >&2; exit 255 ;;
  esac
elif [[ "$*" == *'GitHubTokenSecretName'* ]]; then
  [[ "$SCENARIO" == parameter-failure ]] && { echo 'lookup denied' >&2; exit 255; }
  case "$SCENARIO" in
    existing-empty) printf '\n' ;;
    existing-none) printf 'None\n' ;;
    *) printf '%s\n' 'existing-secret-name' ;;
  esac
elif [[ "$*" == *'Outputs'* ]]; then
  printf 'https://example.invalid\n'
fi
AWS
chmod +x "$work/bin/aws"

reset_logs() {
  : > "$work/sam.log"; : > "$work/aws.log"; : > "$work/secret-retrieval.log"
  : > "$work/out"; : > "$work/err"
}
assert_no_secret_disclosure_or_retrieval() {
  [[ ! -s "$work/secret-retrieval.log" ]]
  ! grep -R -F -- "$secret_sentinel" "$work"
  ! grep -a -E 'secretsmanager[[:space:]]+get-secret-value' "$work/aws.log"
}
run_case() {
  local scenario="$1" explicit="${2:-}" expected="$3"
  reset_logs
  local -a env=(env "PATH=$work/bin:$PATH" "SAM_LOG=$work/sam.log" "AWS_LOG=$work/aws.log" "SECRET_RETRIEVAL_LOG=$work/secret-retrieval.log" "SECRET_SENTINEL=$secret_sentinel" "SCENARIO=$scenario" "IGOR_STACK_NAME=test-stack" "IGOR_SOURCE_REVISION=test-revision")
  if [[ "$explicit" == __unset__ ]]; then
    "${env[@]}" bash "$repo_root/scripts/deploy.sh" >"$work/out" 2>"$work/err"
  else
    "${env[@]}" "IGOR_GITHUB_TOKEN_SECRET_NAME=$explicit" bash "$repo_root/scripts/deploy.sh" >"$work/out" 2>"$work/err"
  fi
  python3 - "$work/sam.log" "$expected" <<'PY'
import sys
args=open(sys.argv[1], 'rb').read().split(b'\0')
assert ('GitHubTokenSecretName=' + sys.argv[2]).encode() in args, args
PY
  assert_no_secret_disclosure_or_retrieval
}

# Existing stack + omitted variable preserves its current secret-name parameter.
run_case existing __unset__ existing-secret-name
# Existing stack + omitted variable preserves a valid empty no-credential parameter.
run_case existing-empty __unset__ ''
# AWS CLI text rendering of the same empty parameter as None is also no-credential.
run_case existing-none __unset__ ''
# Existing stack + explicit variable uses the supplied secret name.
run_case existing replacement-secret-name replacement-secret-name
# New stack + omitted variable omits the override, allowing template's empty default.
reset_logs
env "PATH=$work/bin:$PATH" "SAM_LOG=$work/sam.log" "AWS_LOG=$work/aws.log" "SECRET_RETRIEVAL_LOG=$work/secret-retrieval.log" "SECRET_SENTINEL=$secret_sentinel" SCENARIO=new IGOR_STACK_NAME=test-stack IGOR_SOURCE_REVISION=test-revision bash "$repo_root/scripts/deploy.sh" >"$work/out" 2>"$work/err"
python3 - "$work/sam.log" <<'PY'
import sys
args=open(sys.argv[1], 'rb').read().split(b'\0')
assert not any(arg.startswith(b'GitHubTokenSecretName=') for arg in args), args
PY
assert_no_secret_disclosure_or_retrieval
# Failed existing-parameter lookup stops before SAM deployment and does not retrieve content.
reset_logs
if env "PATH=$work/bin:$PATH" "SAM_LOG=$work/sam.log" "AWS_LOG=$work/aws.log" "SECRET_RETRIEVAL_LOG=$work/secret-retrieval.log" "SECRET_SENTINEL=$secret_sentinel" SCENARIO=parameter-failure IGOR_STACK_NAME=test-stack IGOR_SOURCE_REVISION=test-revision bash "$repo_root/scripts/deploy.sh" >"$work/out" 2>"$work/err"; then
  echo 'expected parameter lookup failure' >&2; exit 1
fi
grep -q 'Unable to read the existing GitHubTokenSecretName parameter; refusing to deploy.' "$work/err"
[[ ! -s "$work/sam.log" ]]
assert_no_secret_disclosure_or_retrieval
# Failed/unauthorized stack lookup stops before SAM deployment and does not retrieve content.
reset_logs
if env "PATH=$work/bin:$PATH" "SAM_LOG=$work/sam.log" "AWS_LOG=$work/aws.log" "SECRET_RETRIEVAL_LOG=$work/secret-retrieval.log" "SECRET_SENTINEL=$secret_sentinel" SCENARIO=stack-failure IGOR_STACK_NAME=test-stack IGOR_SOURCE_REVISION=test-revision bash "$repo_root/scripts/deploy.sh" >"$work/out" 2>"$work/err"; then
  echo 'expected stack lookup failure' >&2; exit 1
fi
grep -q 'Unable to determine whether stack test-stack exists; refusing to deploy.' "$work/err"
[[ ! -s "$work/sam.log" ]]
assert_no_secret_disclosure_or_retrieval
echo 'deploy.sh regression tests passed: sentinel absent and no secret-value retrieval'
# Required command checks run before a stack lookup; absence cannot be mistaken for a new stack.
mkdir -p "$work/no-aws"
ln -sf "$work/bin/sam" "$work/no-aws/sam"
reset_logs
if env "PATH=$work/no-aws" SAM_LOG="$work/sam.log" AWS_LOG="$work/aws.log" SECRET_RETRIEVAL_LOG="$work/secret-retrieval.log" SCENARIO=existing IGOR_STACK_NAME=test-stack IGOR_SOURCE_REVISION=test-revision /bin/bash "$repo_root/scripts/deploy.sh" >"$work/out" 2>"$work/err"; then
  echo 'expected missing AWS CLI failure' >&2; exit 1
fi
grep -q 'AWS CLI is required' "$work/err"
[[ ! -s "$work/aws.log" ]]
assert_no_secret_disclosure_or_retrieval
