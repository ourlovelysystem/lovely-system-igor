#!/usr/bin/env bash
# Shell regression tests for scripts/deploy.sh. They mock AWS/SAM and never use a token value.
set -euo pipefail
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/bin"

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
if [[ "$*" == *'describe-stacks'* && "$*" == *'StackId'* ]]; then
  case "${SCENARIO:?}" in
    existing|parameter-failure) printf 'stack-id\n' ;;
    new) echo 'An error occurred (ValidationError): Stack with id test-stack does not exist' >&2; exit 255 ;;
  esac
elif [[ "$*" == *'GitHubTokenSecretName'* ]]; then
  [[ "$SCENARIO" == parameter-failure ]] && { echo 'lookup denied' >&2; exit 255; }
  printf '%s\n' 'existing-secret-name'
elif [[ "$*" == *'Outputs'* ]]; then
  printf 'https://example.invalid\n'
fi
AWS
chmod +x "$work/bin/aws"

run_case() {
  local scenario="$1" explicit="${2:-}" expected="$3"
  : > "$work/sam.log"; : > "$work/aws.log"
  local -a env=(env "PATH=$work/bin:$PATH" "SAM_LOG=$work/sam.log" "AWS_LOG=$work/aws.log" "SCENARIO=$scenario" "IGOR_STACK_NAME=test-stack" "IGOR_SOURCE_REVISION=test-revision")
  if [[ "$explicit" == __unset__ ]]; then
    "${env[@]}" bash "$repo_root/scripts/deploy.sh" >"$work/out" 2>"$work/err"
  else
    "${env[@]}" "IGOR_GITHUB_TOKEN_SECRET_NAME=$explicit" bash "$repo_root/scripts/deploy.sh" >"$work/out" 2>"$work/err"
  fi
  python3 - "$work/sam.log" "$expected" <<'PY'
import sys
args=open(sys.argv[1],'rb').read().split(b'\0')
assert ('GitHubTokenSecretName='+sys.argv[2]).encode() in args, args
PY
  ! grep -q 'token contents' "$work/out" "$work/err"
}

# Existing stack + omitted variable preserves its current secret-name parameter.
run_case existing __unset__ existing-secret-name
# Existing stack + explicit variable uses the supplied secret name.
run_case existing replacement-secret-name replacement-secret-name
# New stack + omitted variable omits the override, allowing template's empty default.
: > "$work/sam.log"; : > "$work/aws.log"
env "PATH=$work/bin:$PATH" "SAM_LOG=$work/sam.log" "AWS_LOG=$work/aws.log" SCENARIO=new IGOR_STACK_NAME=test-stack IGOR_SOURCE_REVISION=test-revision bash "$repo_root/scripts/deploy.sh" >"$work/out" 2>"$work/err"
python3 - "$work/sam.log" <<'PY'
import sys
args=open(sys.argv[1],'rb').read().split(b'\0')
assert not any(arg.startswith(b'GitHubTokenSecretName=') for arg in args), args
PY
# A failed existing-parameter lookup must stop before SAM deploy and not substitute empty.
: > "$work/sam.log"; : > "$work/aws.log"
if env "PATH=$work/bin:$PATH" "SAM_LOG=$work/sam.log" "AWS_LOG=$work/aws.log" SCENARIO=parameter-failure IGOR_STACK_NAME=test-stack IGOR_SOURCE_REVISION=test-revision bash "$repo_root/scripts/deploy.sh" >"$work/out" 2>"$work/err"; then
  echo 'expected parameter lookup failure' >&2; exit 1
fi
grep -q 'Unable to read the existing GitHubTokenSecretName parameter; refusing to deploy.' "$work/err"
[[ ! -s "$work/sam.log" ]]
! grep -q 'token contents' "$work/out" "$work/err"
echo 'deploy.sh regression tests passed'
# Required command checks run before a stack lookup; absence cannot be mistaken for a new stack.
mkdir -p "$work/no-aws"
ln -sf "$work/bin/sam" "$work/no-aws/sam"
: > "$work/aws.log"
if env "PATH=$work/no-aws" SAM_LOG="$work/sam.log" AWS_LOG="$work/aws.log" SCENARIO=existing IGOR_STACK_NAME=test-stack IGOR_SOURCE_REVISION=test-revision /bin/bash "$repo_root/scripts/deploy.sh" >"$work/out" 2>"$work/err"; then
  echo 'expected missing AWS CLI failure' >&2; exit 1
fi
grep -q 'AWS CLI is required' "$work/err"
[[ ! -s "$work/aws.log" ]]
