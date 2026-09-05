# Igor

Igor is an AWS-resident conversational coding and infrastructure worker. Tell
Igor the outcome you want. Its isolated worker can inspect AWS, write code,
run development and AWS CLI commands, create or change infrastructure, observe
failures, correct its work, and preserve the resulting code and evidence.

## Truth contract

Igor reports exactly one terminal state:

- `WORKING` — cited execution commands and post-change verification succeeded.
- `FAILED` — Igor attempted the work and captured the failing stage and error.
- `BLOCKED` — permissions, model access, quota, or another external prerequisite stopped it.
- `INCOMPLETE` — reserved for work that ended without sufficient evidence.

`QUEUED` and `RUNNING` are non-terminal states. Every terminal job points to a
JSON evidence record in S3. A model's claim is never accepted as proof.

## AWS components

- Lambda Function URL: authenticated control API
- Lambda Function URL: public dashboard shell with no AWS authority
- Cognito and API Gateway: operator login and authenticated dashboard API
- Lambda: persistent conversational tool loop
- DynamoDB: durable conversations and job records
- CodeBuild: isolated worker
- Bedrock: configurable conversational and execution model
- AWS CLI and development tools: general execution inside CodeBuild
- S3: complete worker workspace archives and evidence
- CloudWatch: Lambda and CodeBuild logs
- IAM: separate control, worker, legacy deployment, and passable workload roles

AgentCore is not required for this implementation. Generated commands execute
inside an ephemeral CodeBuild worker, not inside the conversational Lambda.

## Deploy

Prerequisites: an AWS account, AWS CLI, AWS SAM CLI, and Bedrock access for the
selected model. The default region is `us-east-1` and the default model is
`global.openai.gpt-5.6-terra`; both are configurable.

```bash
./scripts/deploy.sh
```

The script prints the dashboard and authenticated CLI API URLs. Create the
first invited dashboard operator, then open the dashboard URL:

```bash
./scripts/create-operator.sh you@example.com
```

Cognito emails a temporary password. The dashboard asks for a permanent
password on first sign-in. Public account creation is disabled.

The CLI remains available. Submit an idea:

```bash
python3 -m pip install boto3
python3 scripts/igor.py \
  --url "$(aws cloudformation describe-stacks --stack-name igor \
    --query 'Stacks[0].Outputs[?OutputKey==`IgorUrl`].OutputValue' --output text)" \
  submit \
  "Build a tiny service that returns a friendly greeting and the current UTC time."
```

Check the returned job ID:

```bash
python3 scripts/igor.py --url "$IGOR_URL" status JOB_ID
```

## Develop

```bash
python3 -m unittest discover -s tests -v
```

See [docs/architecture.md](docs/architecture.md) for the data flow and
[LOGBOOK.md](LOGBOOK.md) for decisions and observed results.

## Authority and boundaries

- The operator's natural-language objective directs the task; infrastructure
  types are not hard-coded into the conversation tool.
- The worker and its passable workload role have AWS `AdministratorAccess`.
  Igor can operate every AWS service, including IAM and existing resources.
- There is no IAM boundary protecting Igor's own control plane from Igor. The
  operator's direction is the authority boundary.
- The execution prompt tells Igor to minimize disclosure of credentials and
  secret values, but IAM does not prevent access when the task requires it.
- Every worker workspace is archived to S3 before the job becomes terminal.
- `WORKING` with changes requires cited successful verification after the last
  change. Claimed public endpoints receive a separate HTTP probe from Igor.
- The worker reads this public repository at build time.
- The CLI control URL uses AWS IAM signing. The dashboard API requires a
  Cognito token from an invited operator.
- The dashboard shell is public static HTML. It has no AWS authority and cannot
  submit or read jobs without an authenticated operator token.
