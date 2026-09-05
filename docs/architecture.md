# Architecture

## Request path

1. An operator signs in to the dashboard through Cognito, or uses the
   IAM-authenticated CLI.
2. API Gateway validates dashboard tokens before invoking Igor.
3. The conversational Lambda loads durable context, calls Terra, and submits
   the operator's complete objective through one general execution tool.
4. The control Lambda writes a `QUEUED` record and starts CodeBuild.
5. The worker changes the job to `RUNNING` and starts an agentic Terra loop.
6. Terra uses `run_command` to inspect AWS, create files, operate services,
   observe failures, and verify the resulting live state.
7. Igor validates Terra's terminal evidence request. Changed systems require a
   cited successful verification command after the last change.
8. Igor independently probes every claimed public HTTP endpoint.
9. Igor archives the complete worker workspace and command transcript to S3,
   then records `WORKING`, `FAILED`, `BLOCKED`, or `INCOMPLETE` in DynamoDB.

## Trust boundaries

The public dashboard Lambda serves only static HTML and configuration; it has
no access to jobs, conversations, or deployment services. Cognito disallows
public sign-up, and API Gateway admits only tokens issued to invited operators.
The separate IAM Function URL preserves scripted access.

The conversational Lambda can call Bedrock, store conversations, and invoke the
control Lambda. It cannot deploy workloads directly.

The control Lambda can create jobs but cannot deploy workloads. The ephemeral
CodeBuild worker has AWS managed `AdministratorAccess`. Igor also provides an
administrator workload role and EC2 instance profile that the worker may pass
to services. No IAM policy protects Igor's own stack or other existing account
resources from the worker; the operator's objective is the authority boundary.

The generality is intentional: the execution model may run AWS CLI, Python,
git, curl, build tools, and generated code inside CodeBuild. Its command log and
workspace archive make the work inspectable. This is account-administrator
authority and is materially more authority than the original pilot.

## Evidence gate

`WORKING` requires successful command evidence. If changes were made, at least
one cited `verify` command must have run successfully after the last change
command. Every claimed public endpoint must also return HTTP 2xx to Igor's
independent probe. The evidence object records the objective, model, command
transcript, cited command IDs, resources, endpoints, independent probes, and
workspace archive URI.
