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
