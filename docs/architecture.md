# Architecture

## Request path

1. An IAM-authenticated caller submits an idea to the control Lambda.
2. The control Lambda writes a `QUEUED` record and starts CodeBuild.
3. The worker changes the job to `RUNNING` and asks Bedrock for `app.py`.
4. Igor parses and statically validates the generated source without executing it.
5. Igor uploads the source bundle and creates a per-job CloudFormation stack.
6. Igor probes the stack's live Function URL.
7. Igor writes evidence to S3, then sets `WORKING`, `FAILED`, or `BLOCKED`.

## Trust boundaries

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

