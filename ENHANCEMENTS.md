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

| Release | Outcome | Included enhancements | Status | Functional revision |
| --- | --- | --- | --- | --- |
| Upload experience v2 | Faster, inspectable uploads that survive conversation navigation safely | IGOR-001, IGOR-002, IGOR-003, IGOR-004, IGOR-005 | PROPOSED | — |
| Multimodal conversations v1 | Understand the operator's screenshots, images, PDFs, and uploaded files | IGOR-006 | RELEASED | `f6b26240103826f9392b14ef02c4a576df208b44` |
| Live directed work v1 | Make coding and infrastructure work inspectable, steerable, and recoverable across jobs | IGOR-008, IGOR-011, IGOR-012, IGOR-013 | IN PROGRESS | Recorded in deployed stack SourceRevision |
| Responsive execution v1 | Reduce visible latency and avoid unnecessary worker starts without sacrificing evidence | IGOR-014, IGOR-015, IGOR-016, IGOR-017 | READY | — |
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

- Status: `RELEASED`
- Candidate release: Multimodal conversations v1
- Comparison capability: Read screenshots, images, PDFs, and uploaded files
  directly.
- Released behavior: Small supported images are loaded from private S3 into the
  current Bedrock request. Documents, large images, and unsupported files are
  routed by private S3 location to the execution worker; they are not sent
  directly to Bedrock. Functional revision
  `f6b26240103826f9392b14ef02c4a576df208b44` was verified for this behavior.
  Subsequently, evidence-record revision
  `66d080d4a6bd45750a2182ba48d8a34f3714ca61` was deployed to the existing
  `igor` stack to record the matrix evidence. The latter is a ledger/evidence
  revision, not the functional revision. This avoids treating a release record's
  own deployment as new functional evidence.
- Intended outcome: The operator can attach a supported file and receive an
  answer grounded in its actual contents, regardless of whether the conversation
  model or worker performs the inspection.
- Acceptance evidence:
  - Live tests cover screenshots, common image formats, PDFs, text documents,
    structured data, HTML, and a file too large for direct model input.
  - Igor identifies which component inspected each file and reports unsupported,
    corrupt, encrypted, or truncated input plainly.
  - File-derived claims cite the filename and a useful location such as page,
    row range, sheet, or section when the format permits it.

- Live matrix evidence (2026-09-06):
  - Screenshot `screenshot.png`: **inspected successfully** by
    `conversation-model`; the live response cited `screenshot.png` and read
    exact visible text `SCREENSHOT OK` (conversation
    `matrix3501acc5593c4c0ea1b3414cd5b2a459`).
  - Common images: `photo.jpg` (**inspected successfully**, `JPEG_OK`),
    `graphic.webp` (**inspected successfully**, `WEBP_OK`), and `animation.gif`
    (**inspected successfully**, `GIF_OK`) were inspected by
    `conversation-model`. Each live response named the file and component; the
    initial GIF89a signature-routing defect was concretely diagnosed, fixed, and
    retested (conversation `matrix7e0f7e5065d4424dac2d8abea2f8e4de`).
  - PDF `report.pdf`: execution worker job
    `c5c8f8b5a40548129691c1ed93fcdb0c` reached durable `stage=complete`
    (terminal status `WORKING`) with evidence
    `s3://igor-evidencebucket-kuuvbcaqekxt/jobs/c5c8f8b5a40548129691c1ed93fcdb0c/evidence.json`.
    It reported the page-one text `PDFDOC OK PAGE ONE` and a **concrete
    unsupported/non-conformant result**: the 396-byte PDF has no `xref` or
    `startxref`; `/Encrypt` is absent and it ends in `%%EOF`. The worker named
    itself and cited page 1; parser/renderer availability was explicitly recorded
    as a limitation.
  - Text document `memo.md`: execution worker job
    `a414faa08da04fb497802ab645385c68` reached durable `stage=complete`
    (terminal status `WORKING`) with evidence
    `s3://igor-evidencebucket-kuuvbcaqekxt/jobs/a414faa08da04fb497802ab645385c68/evidence.json`.
    It successfully inspected all 32 bytes and reported `TEXTDOC OK` at heading
    `# Memo` / section one.
  - Structured data `inventory.csv`: execution worker job
    `b41cab0429c646d389a92c0339f5ab8c` reached durable `stage=complete`
    (terminal status `WORKING`) with evidence
    `s3://igor-evidencebucket-kuuvbcaqekxt/jobs/b41cab0429c646d389a92c0339f5ab8c/evidence.json`.
    It successfully parsed the 28-byte CSV: header row 1 `title,amount`, rows
    2--3 `ALPHA,7` and `BETA,9`.
  - HTML `page.html`: execution worker job
    `c27ac35ee8b54483aeac4fd2955d425d` reached durable `stage=complete`
    (terminal status `WORKING`) with evidence
    `s3://igor-evidencebucket-kuuvbcaqekxt/jobs/c27ac35ee8b54483aeac4fd2955d425d/evidence.json`.
    It successfully inspected line 1 / the sole HTML document and reported its
    `h1` content `HTMLDOC OK`.
  - Oversized image `large.png`: execution worker job
    `73690a7045e54860887ecc537460ae8f` reached durable `stage=complete`
    (terminal status `WORKING`) with evidence
    `s3://igor-evidencebucket-kuuvbcaqekxt/jobs/73690a7045e54860887ecc537460ae8f/evidence.json`.
    It verified the private PNG is 20,837,457 bytes (above the 3,500,000-byte
    direct-image limit), 2000x2000, then successfully inspected it through the
    execution worker / Nova Lite derivative path. It reported no readable text
    or identifiable object and cited coordinate regions (for example,
    lower-right for brightest yellow/green and upper-/lower-left for darkest
    blue/purple).
  - The five worker-job durable records, their attachment metadata, all completed
    command events, and immutable evidence objects were re-read before this
    release decision. No replacement job was created because each existing job
    supplied a successful live inspection or the required concrete unsupported
    result. Matrix command evidence from the original upload/routing flow remains
    in execution records `cmd-019`, `cmd-020`, and `cmd-023`; the source objects
    remain private under `attachments/live-matrix/...`.

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


### IGOR-014 — One worker job per directed request

- Status: `READY`
- Candidate release: Responsive execution v1
- Observed problem: A single conversation request containing several
  worker-routed files can create a separate CodeBuild job for each file. Each job
  incurs its own queue delay, worker startup, workspace initialization, and
  evidence lifecycle.
- Intended outcome: One operator message creates at most one execution-worker
  job containing the complete request and every attachment assigned to the
  worker.
- Acceptance evidence:
  - A live request containing at least five worker-routed files creates exactly
    one worker job.
  - The job reports an individual inspection result for every attached file.
  - One unsupported or corrupt file does not erase successful results for the
    other files.
  - Files remain associated with the originating conversation and request.
  - The terminal evidence maps every attachment to its result.

### IGOR-015 — Stream conversational responses

- Status: `READY`
- Candidate release: Responsive execution v1
- Observed problem: The dashboard waits for the complete Bedrock response before
  displaying any assistant text, so useful output remains invisible while the
  model is generating it.
- Intended outcome: Display ordered response content as Bedrock produces it,
  while preserving one authoritative completed message in conversation history.
- Acceptance evidence:
  - A controlled long response displays its first content before model
    completion.
  - Streamed fragments are ordered and assemble into the exact durable assistant
    message.
  - Tool requests and execution-worker handoffs remain valid during streaming.
  - Interrupted or failed streams are identified plainly and never appear as
    complete answers.
  - Reopening the conversation displays the authoritative assembled response
    without duplicated fragments.

### IGOR-016 — Fast path for bounded work

- Status: `READY`
- Candidate release: Responsive execution v1
- Observed problem: Small, bounded inspections pay the same CodeBuild
  provisioning cost as repository modification and infrastructure deployment.
  The observed worker startup delay alone was approximately 28 seconds.
- Intended outcome: Execute explicitly bounded, non-mutating inspections through
  lower-startup compute while retaining the full CodeBuild worker for coding,
  deployment, and other unrestricted work.
- Acceptance evidence:
  - The eligible task classes and their permission boundary are explicit and
    testable.
  - A controlled sample of at least 20 eligible tasks records submission,
    acceptance, first-action, and completion latency; median time to first action
    is below 5 seconds and p95 is below 10 seconds.
  - Coding, publication, deployment, arbitrary shell work, and tasks exceeding
    the bound always use the full execution worker.
  - Fast-path work produces the same durable events, evidence location, and
    honest terminal-status rules as full-worker work.
  - Classification uncertainty falls back to the full worker rather than
    expanding fast-path authority.

### IGOR-017 — Worker latency and capacity telemetry

- Status: `READY`
- Candidate release: Responsive execution v1
- Observed problem: Igor exposes timestamps but does not summarize queue delay,
  worker startup, execution duration, concurrency pressure, or which phase
  caused a slow job.
- Intended outcome: Make worker performance measurable before purchasing larger
  compute, reserved capacity, or quota increases.
- Acceptance evidence:
  - Every worker job records queue time, provisioning/startup time, time to first
    action, active execution time, and total duration.
  - The dashboard distinguishes queued, provisioning, running, and terminal
    phases and shows their elapsed times.
  - A multi-job live test records maximum simultaneous workers and identifies
    account or project concurrency throttling plainly.
  - Performance summaries contain no prompt contents, file contents,
    credentials, or secret values.
  - A release decision records whether measurements justify larger compute,
    increased concurrency, reserved capacity, or no capacity change.

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
