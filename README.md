# Igor

Igor is an AWS-resident coding worker. Give it an idea; it either returns a
verified deployment or an honest failure record.

This first vertical slice builds one kind of system: a dependency-free Python
HTTP Lambda. It generates the handler with Amazon Bedrock, deploys it in a
per-job CloudFormation stack, and probes the live URL. A job becomes `WORKING`
only after the live probe returns a 2xx response.

## Truth contract

Igor reports exactly one terminal state:

- `WORKING` — static checks, CloudFormation deployment, and live HTTP probe passed.
- `FAILED` — Igor attempted the work and captured the failing stage and error.
- `BLOCKED` — permissions, model access, quota, or another external prerequisite stopped it.
- `INCOMPLETE` — reserved for work that ended without sufficient evidence.

`QUEUED` and `RUNNING` are non-terminal states. Every terminal job points to a
JSON evidence record in S3. A model's claim is never accepted as proof.

## AWS components

- Lambda Function URL: authenticated control API
- DynamoDB: durable job record
- CodeBuild: isolated worker
- Bedrock: configurable code-generation model
- CloudFormation: generated workload deployment
- S3: source bundles and evidence
- CloudWatch: Lambda and CodeBuild logs
- IAM: separate control, worker, deployment, and generated-app roles

AgentCore is intentionally not in this first slice. CodeBuild is the safer
execution boundary for generated work. An AgentCore orchestrator can be added
later without changing the job or evidence contract.

## Deploy

Prerequisites: an AWS account, AWS CLI, AWS SAM CLI, and Bedrock access for the
selected model. The default region is `us-east-1` and the default model is
`global.openai.gpt-5.6-terra`; both are configurable.

```bash
./scripts/deploy.sh
```

The script prints the authenticated Igor API URL. Submit an idea:

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

## Current boundaries

- One generated AWS Lambda per job; no arbitrary infrastructure yet.
- The generated handler may import only `json` and has no AWS permissions.
- The worker reads this public repository at build time.
- The control API uses AWS IAM signing; it is not public.
- Deployment has not been claimed until it has been run in an AWS account.
