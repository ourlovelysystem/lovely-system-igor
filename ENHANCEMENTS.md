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
| Multimodal conversations v1 | Understand the operator's screenshots, images, PDFs, and uploaded files | IGOR-006 | IN PROGRESS | — |
| Live directed work v1 | Make coding and infrastructure work inspectable, steerable, and recoverable across jobs | IGOR-008, IGOR-011, IGOR-012, IGOR-013 | IN PROGRESS | Recorded in deployed stack SourceRevision |
| Connected capabilities v1 | Research the web, use authorized applications, and create reusable artifacts | IGOR-007, IGOR-009, IGOR-010 | PROPOSED | — |

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

### IGOR-006 — Direct multimodal file understanding

- Status: `IN PROGRESS`
- Candidate release: Multimodal conversations v1
- Comparison capability: Read screenshots, images, PDFs, and uploaded files
  directly.
- Current state: Small supported images and documents can be loaded from private
  S3 into the current Bedrock request. Large and unsupported files are passed by
  private S3 location to the worker. Image understanding has been observed in
  deployment; the complete file matrix has not.
- Intended outcome: The operator can attach a supported file and receive an
  answer grounded in its actual contents, regardless of whether the conversation
  model or worker performs the inspection.
- Acceptance evidence:
  - Live tests cover screenshots, common image formats, PDFs, text documents,
    structured data, and a file too large for direct model input.
  - Igor identifies which component inspected each file and reports unsupported,
    corrupt, encrypted, or truncated input plainly.
  - File-derived claims cite the filename and a useful location such as page,
    row range, sheet, or section when the format permits it.

- Live matrix evidence (2026-09-06; deployed revision `f1173cc815f324dc18730603afce8776f3229bad`):
  - Screenshot `screenshot.png`: **inspected successfully** by `conversation-model`;
    response cited `screenshot.png` and read exact visible text `SCREENSHOT OK`
    (live conversation `matrix3501acc5593c4c0ea1b3414cd5b2a459`).
  - Common images: `photo.jpg` was **inspected successfully** by
    `conversation-model` (`JPEG_OK`); `graphic.webp` was **inspected successfully**
    by `conversation-model` (`WEBP_OK`); and `animation.gif` was **inspected
    successfully** after the GIF89a regression correction by `conversation-model`
    (`GIF_OK`, conversation `matrix7e0f7e5065d4424dac2d8abea2f8e4de`). Each live
    response named the file and component. The initial GIF89a run was concretely
    diagnosed as a bad signature-routing defect, fixed and retested.
  - `report.pdf` (PDF; worker job `c5c8f8b5a40548129691c1ed93fcdb0c`),
    `memo.md` (text document; `a414faa08da04fb497802ab645385c68`),
    `inventory.csv` (structured data; `b41cab0429c646d389a92c0339f5ab8c`),
    `page.html` (text document; `c27ac35ee8b54483aeac4fd2955d425d`), and
    `large.png` (20,837,457 bytes, above the 3,500,000-byte direct-image limit;
    `73690a7045e54860887ecc537460ae8f`) were live-uploaded to private S3 and
    correctly routed to `execution-worker`. The live conversation responses named
    the component and queued job IDs. At recording time those jobs remained
    `QUEUED`; they have not produced a file inspection or a concrete unsupported
    result. They therefore do **not** satisfy the matrix acceptance criterion.
  - Matrix command evidence is retained in execution records `cmd-019`, `cmd-020`,
    and `cmd-023`; attachment keys are private `attachments/live-matrix/...` S3
    objects. This item remains IN PROGRESS and is not released.

### IGOR-007 — Web research with linked sources

- Status: `READY`
- Candidate release: Connected capabilities v1
- Comparison capability: Search the web and provide linked sources.
- Observed problem: Igor has no dedicated web retrieval and citation path.
- Intended outcome: Igor can research current public information and return
  claims with inspectable source links.
- Acceptance evidence:
  - A current-information request produces working links to the supporting pages.
  - Igor distinguishes sourced facts, inference, and unavailable evidence.
  - Retrieved content is treated as untrusted input rather than instructions.

### IGOR-008 — Interactive code workspace

- Status: `IN PROGRESS`
- Candidate release: Live directed work v1
- Comparison capability: Inspect, edit, and test code in a workspace while
  showing the resulting file changes.
- Current state: The isolated worker can clone a repository, edit it, run
  commands, test changes, archive the workspace, and use GitHub credentials. The
  dashboard does not yet provide an interactive workspace or rendered diff.
- Intended outcome: The operator can see the repository, commands, tests, and
  proposed changes associated with a job before or after publication.
- Acceptance evidence:
  - Every coding job identifies its repository and starting revision.
  - The dashboard exposes changed files, a readable diff, commands, and test
    results without requiring access to the CodeBuild container.
  - Published changes identify the resulting branch or commit.

### IGOR-009 — Authorized applications and browser sessions

- Status: `PROPOSED`
- Candidate release: Connected capabilities v1
- Comparison capability: Use connected applications and authenticated browser
  sessions.
- Open design decision: Define which applications are useful and whether each
  uses an API connector, delegated credentials, or an interactive browser.
- Intended outcome: Igor can perform operator-directed work in approved external
  services without asking the operator to copy credentials into chat.
- Acceptance evidence:
  - Every connection identifies its granted permissions and authenticated
    identity.
  - Igor requests explicit direction before externally consequential writes.
  - Revocation stops new access, and actions retain an inspectable audit record.

### IGOR-010 — Create and preview reusable artifacts

- Status: `READY`
- Candidate release: Connected capabilities v1
- Comparison capability: Create and preview documents, spreadsheets,
  presentations, and images.
- Intended outcome: Igor produces downloadable, visually inspectable artifacts
  rather than only describing how to create them.
- Acceptance evidence:
  - Live tests create and preview a document, spreadsheet, presentation, and
    image.
  - Structured artifacts remain editable in their native formats.
  - Igor reports the durable location and revision of each completed artifact.

### IGOR-011 — Visible work while a job runs

- Status: `READY`
- Candidate release: Live directed work v1
- Comparison capability: Keep the operator informed while working instead of
  merely returning a job ID.
- Current state: The worker atomically appends durable stage, command purpose,
  round, completion, exit-status, publication, deployment, and failure events;
  the dashboard polls and displays them. Live acceptance job
  `c3e6baba0a2c4733a1ee8480f5256a0f` retained 40 durable events after terminal
  completion, including current activity, command starts/completions and exit
  statuses, successful and deliberately failed verification (exit 7), actual
  publication, actual deployment, immediate failure reporting, and the terminal
  event. Its evidence contains independent GitHub ref and CloudFormation
  SourceRevision checks for `80c735c1ebc20fb48aa649666900fb6f2e96cc6f`.
- Intended outcome: The conversation itself shows what Igor is doing, what has
  completed, what is blocked, and what remains.
- Acceptance evidence:
  - A multi-step live job displays meaningful progress before terminal status.
  - Updates correspond to durable worker state rather than invented model prose.
  - Failures identify the active stage and last completed action.

### IGOR-012 — Mid-task operator steering

- Status: `PROPOSED`
- Candidate release: Live directed work v1
- Comparison capability: Accept corrections while a task is underway.
- Observed problem: A submitted worker job currently runs from one fixed
  objective; a correction becomes a separate conversation turn or replacement
  job rather than input to the active job.
- Intended outcome: The operator can amend, pause, resume, or cancel active work,
  and Igor acknowledges the instruction at a defined execution boundary.
- Acceptance evidence:
  - The dashboard accepts a correction while a multi-step job is running.
  - The worker records when it received and applied or rejected the correction.
  - Superseded work does not continue making changes after cancellation.
  - The terminal evidence distinguishes the original objective from later
    operator instructions.

### IGOR-013 — Recoverable work across disposable jobs

- Status: `RELEASED`
- Candidate release: Live directed work v1
- Observed problem: Igor jobs use disposable workspaces. `workspace.zip`
  preserves files but excludes `.git`, so an unpushed commit disappears when its
  job ends. A later retry cannot recover that exact commit by SHA and must
  reconstruct the changes manually.
- Intended outcome: Every coding job preserves enough Git-native evidence for a
  later job to restore the exact tested changes and commits automatically.
- Acceptance evidence:
  - A coding job archives the workspace, a binary-safe patch, a Git bundle, and
    a manifest containing repository URL, base revision, resulting revision,
    branch, and push status.
  - Credentials, ignored secrets, and unrelated repository objects are absent
    from recovery artifacts.
  - A retry can identify a source job, restore its work into a fresh workspace,
    and verify the restored tree without requiring the operator to locate S3
    objects or explain Git recovery.
  - If a commit was created, recovery preserves its exact commit object when
    possible; otherwise Igor records why a replacement commit was necessary.
  - An intended push that fails cannot produce `WORKING` merely because local
    tests and a local commit succeeded.
  - An automated test ends one job before push, restores its artifacts in a new
    workspace, and verifies identical file content and commit history.
- Release evidence: Live acceptance completed on 2026-09-06 with source worker job
  `9baee2ad80104779bef9b3654bd4f3ed` and separate recovery worker job
  `f352e021f58e493aabdbd059b673b913` (`recovery_source_job_id` set to the source).
  The source created commit `0431de04e03802f8548c3b45591c5da3e2a269ca`, retained the
  valid `https://github.com/ourlovelysystem/lovely-system-igor.git` origin, and its one
  ordinary push to the pre-existing temporary ref was rejected non-fast-forward. Its durable
  evidence is `s3://igor-evidencebucket-kuuvbcaqekxt/jobs/9baee2ad80104779bef9b3654bd4f3ed/evidence.json`
  and its recovery manifest is `s3://igor-evidencebucket-kuuvbcaqekxt/jobs/9baee2ad80104779bef9b3654bd4f3ed/recovery/manifest.json`.
  The separate recovery worker restored the exact SHA, complete history, tracked text file,
  and binary bytes `00 49 47 4f 52 ff 0a`; it published that unchanged object to
  `igor-013-live-recovered-acceptance`, whose remote SHA was independently verified as
  `0431de04e03802f8548c3b45591c5da3e2a269ca`. Its durable evidence is
  `s3://igor-evidencebucket-kuuvbcaqekxt/jobs/f352e021f58e493aabdbd059b673b913/evidence.json`
  and recovery manifest is `s3://igor-evidencebucket-kuuvbcaqekxt/jobs/f352e021f58e493aabdbd059b673b913/recovery/manifest.json`.
  The disposable-job regression additionally covers safe workspace archival, binary patch,
  bounded Git bundle, ignored-secret exclusion, and `.env` exclusion. The final stack
  SourceRevision is independently read back after publication.

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
