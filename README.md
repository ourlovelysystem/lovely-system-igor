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
- S3: private multipart attachments, complete worker workspace archives, and evidence
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

## Attachments and visible progress

The dashboard accepts images, PDFs, documents, and arbitrary files. Upload bytes
go directly from the browser to Igor's private S3 bucket using multipart upload;
they do not pass through Lambda or API Gateway. Files at or below 32 MiB use one
presigned S3 PUT; larger files use adaptive multipart sizes (while preserving
S3's 10,000-part ceiling) and receive presigned part URLs in bounded batches.
Four parts transfer concurrently. Upload cards show Preparing, Uploading,
Verifying, and Ready states with transferred bytes, rate, elapsed time, ETA, and
an explicit cancel action. Upload cards belong to their originating conversation,
so activity in another conversation never disables its Send button. Igor HEADs
the completed S3 object before marking an attachment ready; cancelled multipart
uploads are aborted and recorded as CANCELLED. Abandoned multipart uploads expire
after seven days.

Supported images and documents within the conversational model's direct-input
threshold are loaded from private S3 and presented to Bedrock as bytes for the
current request. The bytes are not stored in DynamoDB conversation history.
Every other attachment, including
very large files, is passed to the execution worker by private S3 URI so it can
inspect the object with streaming or range-based tools.

While a job runs, the worker records its current stage, plain-language command
purpose, agent round, and completed command count in DynamoDB. The open dashboard
conversation displays those updates every three seconds and replaces them with
the durable terminal report when the job finishes.

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

## GitHub access

Create a fine-grained GitHub token with **Contents: Read and write** access to
the repositories Igor may change. Add **Workflows: Read and write** only if Igor
must change files under `.github/workflows`. Store and deploy the token with:

```bash
./scripts/set-github-token.sh
IGOR_GITHUB_TOKEN_SECRET_NAME=igor/github-token ./scripts/deploy.sh
```

The setup script prompts for the token without placing it in shell history. The
worker retrieves it from AWS Secrets Manager only when Git asks for credentials;
it is not embedded in the repository URL or persisted in the workspace archive.

## Develop

```bash
python3 -m unittest discover -s tests -v
```

See [docs/architecture.md](docs/architecture.md) for the data flow and
[LOGBOOK.md](LOGBOOK.md) for decisions and observed results. Future improvements
and their release grouping live in [ENHANCEMENTS.md](ENHANCEMENTS.md).

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
- Every job retains its originating conversation. Its terminal summary,
  resources, endpoints, and evidence locations are written back as a durable
  Igor message, and the open dashboard conversation refreshes automatically.
- Job progress is durable rather than cosmetic: the worker updates the job record
  before and after each command, and the dashboard displays that record inline.
- The worker reads this public repository at build time.
- The CLI control URL uses AWS IAM signing. The dashboard API requires a
  Cognito token from an invited operator.
- The dashboard shell is public static HTML. It has no AWS authority and cannot
  submit or read jobs without an authenticated operator token.
