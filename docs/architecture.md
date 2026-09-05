# Architecture

## Request path

1. An operator signs in to the dashboard through Cognito, or uses the
   IAM-authenticated CLI.
2. API Gateway validates dashboard tokens before invoking Igor.
3. The conversational Lambda loads durable context, calls Terra, and may invoke
   the bounded build tool when the operator explicitly requests execution.
4. The control Lambda writes a `QUEUED` record and starts CodeBuild.
5. The worker changes the job to `RUNNING` and asks Bedrock for `app.py`.
6. Igor parses and statically validates the generated source without executing it.
7. Igor uploads the source bundle and creates a per-job CloudFormation stack.
8. Igor probes the stack's live Function URL.
9. Igor writes evidence to S3, then sets `WORKING`, `FAILED`, or `BLOCKED`.

## Trust boundaries

The public dashboard Lambda serves only static HTML and configuration; it has
no access to jobs, conversations, or deployment services. Cognito disallows
public sign-up, and API Gateway admits only tokens issued to invited operators.
The separate IAM Function URL preserves scripted access.

The conversational Lambda can call Bedrock, store conversations, and invoke the
control Lambda. It cannot deploy workloads directly.

The control Lambda can create jobs but cannot deploy workloads. The CodeBuild
worker can ask Bedrock and operate only Igor job stacks. CloudFormation assumes
a deployment role. Generated Lambdas receive a separate role containing only
CloudWatch Logs permissions.

Generated source is never imported, tested, or executed by CodeBuild. Static
validation permits only the `json` import and rejects dynamic execution,
filesystem, network, process, reflection, and AWS SDK primitives. The source
executes for the first time in the generated Lambda's minimal role.

## Evidence gate

`WORKING` requires all of these facts:

1. Bedrock returned the required JSON envelope.
2. Python AST parsing and Igor's policy checks passed.
3. CloudFormation reached `CREATE_COMPLETE`.
4. The deployed URL returned HTTP 2xx to Igor's probe.

The evidence object records timestamps, model ID, source SHA-256, stack ID,
endpoint, probe status, and a bounded response excerpt.
