# Reproducible deployment and retirement

This repository is the complete source for redeploying Igor. Retirement removes
the live application but deliberately preserves the state needed for audit or a
later restoration.

## Finalize the source

Before retirement, merge all intended changes to `main`, run `make test`, and
create an immutable Git tag at the exact tested commit. Record that commit in the
retirement inventory. Never put PINs, GitHub tokens, or other secret values in
Git; Igor consumes existing Secrets Manager entries by name and ARN.

## Redeploy

Prerequisites are AWS CLI, AWS SAM CLI, Python 3, Bedrock model access, the
telephone authentication secret, and the separately deployed reference media
stack when telephone service is wanted.

```bash
git checkout <retirement-tag-or-commit>
export IGOR_SOURCE_REVISION="$(git rev-parse HEAD)"
export IGOR_TELEPHONE_AUTH_SECRET_NAME=igor/telephone-auth
export IGOR_REFERENCE_MEETING_TABLE_NAME=<reference-meeting-table>
./scripts/deploy.sh
```

The deployment creates a new application around retained data only when the
retained physical resource names are explicitly imported or migrated. A normal
fresh deployment does not silently adopt retained tables, buckets, or user pools.

## Retirement boundary

The `igor` stack owns the web application, APIs, Lambdas, CodeBuild worker, IAM
roles, Lex resources, and diagnostic audio bucket. It does not own the separate
`AmazonChimeSDKMediaStreams` stack, its telephone number, external Secrets
Manager entries, or workloads produced by prior Igor jobs.

Before deleting Igor, restore the reference media stack to its standalone
ingress and Bedrock response route. Verify its live CloudFormation parameters no
longer contain an Igor ingress or `igor_bridge` response route. This prevents the
retained telephone number from targeting Lambdas that are about to be deleted.

Run the retirement check first:

```bash
./scripts/retire.sh
```

The dry run fails closed if the Igor stack is updating, a worker build is still
running, the reference stack cannot be inspected, or the reference stack still
routes to Igor. It writes `igor-retirement-inventory.json` locally for review.

After reviewing that inventory, delete exactly the Igor stack:

```bash
IGOR_RETIRE_CONFIRM=igor ./scripts/retire.sh --execute
```

The execution archives the final inventory in the retained evidence bucket,
empties only the disposable diagnostic-audio bucket so CloudFormation can remove
it, deletes the `igor` stack, and waits for completion.

## Preserved by default

- job, conversation, and telephone-call DynamoDB tables;
- the versioned evidence and attachment S3 bucket;
- the Cognito operator user pool;
- external Secrets Manager secrets;
- the reference Chime/KVS/ECS/Transcribe stack and telephone number;
- all workloads created by earlier Igor jobs.

These resources can incur storage or service charges. Their later destruction is
a separate, irreversible data-retention decision and is intentionally outside
the retirement script.

## Verify retirement

`aws cloudformation describe-stacks --stack-name igor` should report that the
stack does not exist. The inventory should still identify the retained resources,
and its archived copy should remain readable from the evidence bucket. The
reference media stack should remain healthy on its standalone route.
