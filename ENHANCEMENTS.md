# Igor Enhancement Ledger

This is Igor's durable queue for improvements that are worth preserving but are
not part of the current repair. It groups work into coherent releases without
turning an observation into an implementation commitment.

## Operating rules

- Give every accepted enhancement a permanent `IGOR-NNN` identifier.
- Record the observed problem before proposing a solution.
- An item becomes `READY` only when its acceptance evidence is explicit.
- Assign `READY` items to a release because they belong together, not merely
  because they were requested near each other.
- A release is complete only after its tests pass, its deployed behavior is
  observed, and the deployed commit is recorded here.
- Preserve rejected and superseded items with their disposition instead of
  deleting them.

Statuses: `PROPOSED`, `READY`, `SCHEDULED`, `IN PROGRESS`, `RELEASED`,
`DECLINED`, `SUPERSEDED`.

## Release queue

| Release | Outcome | Included enhancements | Status | Deployed commit |
| --- | --- | --- | --- | --- |
| Upload experience v2 | Faster, inspectable uploads that survive conversation navigation safely | IGOR-001, IGOR-002, IGOR-003, IGOR-004, IGOR-005 | PROPOSED | — |

## Enhancements

### IGOR-001 — Observable upload performance

- Status: `READY`
- Candidate release: Upload experience v2
- Observed problem: The dashboard reports only integer completion percentage,
  so the operator cannot distinguish slow network transfer from preparation,
  signing, or final verification delays.
- Intended outcome: Show the current phase, transferred bytes, transfer rate,
  elapsed time, and estimated time remaining.
- Acceptance evidence:
  - A large upload visibly moves through `Preparing`, `Uploading`, `Verifying`,
    and `Ready`.
  - During transfer, the dashboard shows uploaded/total bytes, MiB/s, elapsed
    time, and an ETA.
  - Phase timings are retained for failure diagnosis without recording file
    contents.

### IGOR-002 — Small-file upload fast path

- Status: `READY`
- Candidate release: Upload experience v2
- Observed problem: Even a small file currently incurs multipart initiation,
  part-signing, upload, completion, and verification requests.
- Intended outcome: Files no larger than 32 MiB use one direct S3 PUT whose
  signed URL is returned by the initial attachment request.
- Acceptance evidence:
  - A file at or below the threshold uses one S3 PUT and no multipart upload.
  - Igor verifies the stored byte count before marking the attachment `READY`.
  - Larger files continue to use multipart upload.

### IGOR-003 — Adaptive multipart uploads

- Status: `READY`
- Candidate release: Upload experience v2
- Depends on: IGOR-001, so performance changes can be measured
- Observed problem: The fixed 100 MiB part size gives medium files too few parts
  to use the browser's four upload workers fully and requests each signed URL
  immediately before its part.
- Intended outcome: Select a smaller part size while preserving S3's 10,000-part
  ceiling, and return signed URLs in bounded batches.
- Acceptance evidence:
  - Part sizing preserves the supported maximum object size and S3 part-count
    limit.
  - Medium files can keep all configured upload workers occupied.
  - Signing pauses do not interrupt active transfer while unsigned parts remain.
  - A controlled before/after upload records throughput and total completion
    time.

### IGOR-004 — Honest composer error state

- Status: `READY`
- Candidate release: Upload experience v2
- Observed problem: A failure from an earlier send remains visible while a new
  attachment uploads successfully, making the old failure look current.
- Intended outcome: Associate errors with the operation that produced them and
  clear or mark them as historical when a new attempt begins.
- Acceptance evidence:
  - Starting a new upload or send cannot present an earlier error as its result.
  - A current failure remains visible until the operator retries or dismisses it.

### IGOR-005 — Safe uploads across conversation navigation

- Status: `READY`
- Candidate release: Upload experience v2
- Observed problem: Starting a new chat hides an active upload without canceling
  it. The global upload counter can keep the new chat's Send button disabled,
  and a completed hidden attachment remains associated with the old conversation
  without a recovery surface.
- Intended outcome: Active uploads remain visible and usable in their originating
  conversation while the operator uses other conversations, with an explicit
  cancel action.
- Acceptance evidence:
  - Starting or selecting another conversation does not lose an upload card.
  - An upload never becomes attached to a different conversation accidentally.
  - Upload activity in one conversation does not disable sending in another.
  - Returning to the originating conversation shows current progress or the
    completed attachment.
  - Canceling aborts the browser request and the S3 multipart upload, and records
    a terminal attachment state.

## Adding an enhancement

Copy this block and use the next identifier:

```markdown
### IGOR-NNN — Short outcome

- Status: `PROPOSED`
- Candidate release: Unassigned
- Observed problem:
- Intended outcome:
- Acceptance evidence:
  -
```
