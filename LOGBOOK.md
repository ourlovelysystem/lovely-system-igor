# Igor logbook

## 2026-09-04 — initial vertical slice

Decision: start with a constrained, verifiable deployment instead of an
open-ended autonomous coding loop.

The pilot accepts an idea, asks a configurable Bedrock model for one Python
Lambda handler, rejects unsafe source shapes, deploys with CloudFormation, and
probes the public workload endpoint. Durable state lives in DynamoDB; evidence
lives in S3.

AgentCore remains a later orchestration layer. It is not required to prove the
first idea-to-working-system path, and generated code must not execute inside a
privileged orchestration runtime.

Local result: unit tests pass. AWS deployment result: not yet run.

## 2026-09-05 — first live job

The Igor control stack deployed successfully in `us-east-1`. Job
`46174842e38840c9a103e9adb349f3f9` was accepted and then reported `FAILED` at
the `generate` stage. Bedrock returned this error:

> This model doesn't support the temperature field. Remove temperature and try again.

Evidence was written to
`s3://igor-evidencebucket-kuuvbcaqekxt/jobs/46174842e38840c9a103e9adb349f3f9/evidence.json`.
The worker did not claim success. The unsupported `temperature` field was
removed and covered by a regression test.

## 2026-09-05 — first verified deployment

After the account's first-use OpenAI model agreement was established, job
`3df7104882d8405384eceeeae1fd011a` reached `WORKING`. Igor generated and
deployed a Lambda, recorded evidence, and its live endpoint returned HTTP 200
with `{"message": "Hello! Welcome to the greeting service."}`.

## 2026-09-05 — conversational web interface

The target was clarified: Igor is intended to be a general-purpose LLM, coding
agent, and AWS infrastructure operator, reachable through a low-friction web
interface and telephone conversation.

This increment adds the first shared conversational core. An invited operator
can hold a persistent Terra conversation in the browser. Terra may invoke the
existing bounded build worker and read job status, but it receives no general
AWS or GitHub authority in this increment. The dashboard displays durable job
state and evidence rather than treating the model's statements as proof.

## 2026-09-05 — operator-directed general execution

The bounded capability catalog was rejected because it made Igor work under
the designer's direction instead of Will Daly's. Igor now exposes one general
execution tool carrying Will's objective verbatim. An ephemeral Terra-driven
CodeBuild worker can inspect AWS, write and run code, operate infrastructure,
recover from observed errors, and verify results.

This is a deliberate authority expansion. The worker receives AWS managed
`PowerUserAccess`, while IAM administration remains excluded. It may pass one
pre-existing workload role. It is explicitly denied updates or deletion of the
`igor` CloudFormation stack and retrieval of Secrets Manager values. Generated
files are archived to S3. `WORKING` requires cited successful post-change
verification, and public endpoints receive an independent HTTP probe.

Local result: 25 tests pass. Live deployment and operator acceptance tests are
pending.

## 2026-09-05 — remove the remaining AWS capability boundary

Will Daly rejected the claim of general AWS execution while the worker still
used `PowerUserAccess`, lacked IAM administration, and was denied access to
Igor's stack and Secrets Manager values. Those restrictions contradicted the
requirement that Igor be able to do anything in AWS under Will's direction.

The worker and passable workload role now receive AWS managed
`AdministratorAccess`. The explicit denies protecting the `igor` stack and
Secrets Manager values were removed. The truth contract remains: administrator
authority permits action, while successful execution and verification evidence
govern what Igor may claim.

## 2026-09-05 — return completed work to the conversation

The first general inspection request returned only a queue receipt. Although
the worker could finish and the work ledger could display its state, Igor did
not deliver the result back into the conversation. This violated the expected
conversational-worker contract: `QUEUED` is acknowledgment, not an answer.

Jobs now retain their originating conversation ID. On every terminal outcome,
the worker writes a durable assistant message containing the summary, status,
job ID, resources, endpoints, evidence URI, and workspace URI. The dashboard
detects the terminal transition and reloads the open conversation automatically.
Local result: 26 tests pass. Live deployment is pending.

## 2026-09-06 — give Igor an independent GitHub identity

Igor could modify a cloned repository inside an isolated job, but it could not
publish those changes because the worker had no GitHub identity. GitHub App
authentication is now supported. The App private key remains in AWS Secrets
Manager; the worker exchanges it for a one-hour installation token only when
Git requests credentials. The token is not embedded in a remote URL or archived
with the job workspace. A setup script stores the App identifiers and private
key, and deployment enables the configured secret for future workers.

Local result: 28 tests pass. GitHub App creation, installation, secret setup,
deployment, and live push verification are pending.

## 2026-09-06 — direct attachments and visible work progress

Will Daly selected two missing capabilities: Igor must read screenshots, images,
PDFs, and uploaded files directly, and it must keep him informed while work is
underway instead of merely returning a job ID. He then made large-upload support
an explicit requirement.

The dashboard now performs private S3 multipart uploads directly from the
browser, using four concurrent parts and visible byte progress. File bytes do not
pass through Lambda or API Gateway. Supported small images and documents are
presented to Bedrock by S3 location. Arbitrary and large files remain private in
S3 and travel with the job as an exact attachment manifest for streaming or
range-based worker inspection.

The worker now writes a plain-language progress message before and after every
command, along with its stage, agent round, and command count. The dashboard
shows that durable job state inline in the active conversation every three
seconds and replaces it with the terminal report when work finishes.

Local result: 36 tests pass. Template, browser, and live AWS validation remain
pending.
