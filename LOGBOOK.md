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
