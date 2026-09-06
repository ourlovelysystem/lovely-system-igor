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
| Responsive execution v1 | Reduce visible latency and avoid unnecessary worker starts without sacrificing evidence | IGOR-014, IGOR-015, IGOR-016, IGOR-017 | IN PROGRESS | IGOR-014: `894525b6142fed748341da9216d8c92bb022707e` |
| Connected capabilities v1 | Research the web, use authorized applications, and create reusable artifacts | IGOR-007, IGOR-009, IGOR-010 | PROPOSED | — |
| Telephone interface v1 | Let the authenticated operator converse with and direct Igor by telephone | IGOR-018 | IN PROGRESS | — |
| Dashboard usability v1 | Make conversation content easier to extract and reuse | IGOR-019 | READY | — |

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

- Status: `RELEASED`
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

- Release evidence (2026-09-06):
  - Functional revision `ce3561e649fa2851bf934f9927f491a52b8f74a5` added
    request-scoped worker-job reuse, passes only execution-worker-routed
    attachments across the control boundary, and requires a complete
    attachment-to-result map in terminal worker evidence. The complete suite
    passed (93 tests plus deployment-script regression) before publication.
  - That exact published `main` revision was deployed **in place** to the
    existing `igor` stack. Independent CloudFormation readback found
    `UPDATE_COMPLETE` and SourceRevision
    `ce3561e649fa2851bf934f9927f491a52b8f74a5`; the remote `main` ref matched.
  - Live authenticated dashboard-API request, conversation
    `055534b02dad427db565244398dd4aab`, uploaded five worker-routed attachments
    (`one.txt`, `two.csv`, `three.md`, `four.html`, and corrupt `broken.pdf`) in
    one message. Exactly one job, `0e5f1a56a6a44de2aa7f4fdfcbd6bc09`, was created
    for that conversation and retained all five attachments. It reached durable
    `WORKING` / `stage=complete`; evidence is
    `s3://igor-evidencebucket-kuuvbcaqekxt/jobs/0e5f1a56a6a44de2aa7f4fdfcbd6bc09/evidence.json`.
  - The immutable terminal evidence maps all five attachment IDs to individual
    results: the four text/structured files were inspected successfully with
    line/row/element locations, while `broken.pdf` was separately recorded as
    corrupt/truncated (invalid header, 41 bytes, no `%%EOF`, not encrypted).
    The corrupt result did not erase the four successful results. A fresh DynamoDB
    and S3 reread verified one related job, five job attachments, and five mapped
    evidence results.
  - This entry is an evidence-only documentation revision made after the
    functional revision was published, deployed, and independently verified. It
    is deliberately not deployed merely to record its own deployment, preventing
    a self-referential deployment-record loop.
  - Corrective release (2026-09-06, issue #4): the prior attachment-only
    reuse condition was broadened to the documented request boundary. Published
    revision `894525b6142fed748341da9216d8c92bb022707e` makes every later
    `execute_task` in one operator request reuse the first durable job, including
    text-only requests; it continues to send worker-routed attachments only once
    and never forwards direct-model images. The full suite passed (110 Python
    tests plus deployment-script regression).
  - That exact functional revision was deployed in place to the existing `igor`
    stack with its existing model, repository, and GitHub secret configuration
    preserved. Independent CloudFormation readback returned `UPDATE_COMPLETE`
    and SourceRevision `894525b6142fed748341da9216d8c92bb022707e`.
  - Live deployed acceptance sent one text-only conversation request,
    conversation `2480081a4fdc4b1b976f7e122a0ad8f4`, explicitly inducing two
    `execute_task` calls. Both returned durable job
    `9360949788b442f481ea541eeb13ed33`; the second result was marked
    `reused_for_request=true`. An independent consistent DynamoDB scan filtered
    by that conversation found exactly one durable worker record, with that same
    job ID and CodeBuild ID
    `WorkerProject-qSb9pRbvusry:3839c838-1b83-4a7d-985b-e9909b5ba6ef`.

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


### IGOR-018 — Telephone conversation and command interface

- Status: `IN PROGRESS`
- Candidate release: Telephone interface v1
- Observed problem: Igor is available through the dashboard but has no telephone
  interface. The operator cannot call Igor, ask spoken questions, hear answers,
  issue commands, or check active work while away from the dashboard.
- Intended outcome: Provide one inbound telephone number through which the
  authenticated operator can hold a turn-based spoken conversation with the
  existing Igor conversation engine. Questions use the normal conversation path;
  commands use Igor's existing execution-worker and evidence path. The telephone
  adapter must not create a separate assistant, command system, or job ledger.
- Initial implementation boundary:
  - Use Amazon Chime SDK PSTN Audio for the phone number, SIP rule, and call
    control; use a voice adapter backed by Amazon Lex V2 and Lambda to exchange
    recognized text and responses with Igor's existing conversation API.
  - Accept inbound calls only. Do not add outbound calling or contact-center
    features in this release.
  - Admit every inbound caller to the greeting and runtime-only DTMF PIN prompt.
    Authenticate only with the per-operator PIN stored in AWS Secrets Manager;
    caller ID is not retained or used as an authentication factor.
  - Answer ordinary questions without confirmation. Before submitting any action
    that can change AWS, GitHub, or another external system, read back the exact
    intended action and require an explicit spoken or DTMF confirmation.
  - Treat uncertain command transcription as an error requiring repetition; do
    not guess and submit a worker job.
  - Do not retain raw call audio by default. Retain the transcript, call ID,
    conversation ID, command confirmation, worker job ID, and normal evidence
    references.
  - If the call ends after job submission, the job continues. Its state remains
    available in the dashboard and through a later authenticated call.
- Depends on: IGOR-014 for request-scoped job deduplication. IGOR-011 progress
  events should be used when reporting active-job status by voice.
- Implementation evidence (2026-09-06):
  - Automated regression/security suite passed (114 tests): runtime Secrets Manager
    retrieval, allowlist rejection, PIN non-retention, low-confidence/refusal no-job
    paths, and conditional single-job confirmation are exercised without recording
    sensitive values.
  - The adapter persists a non-sensitive call ID, pseudonymous caller hash,
    conversation ID, confirmation state, worker job ID, and raw-audio-retained=false
    in a dedicated durable ledger; questions invoke the existing conversation Lambda
    with tools disabled and confirmed commands invoke the existing control Lambda.
  - Stack deployment and a physical call remain required. Do not mark RELEASED until
    the real-call acceptance criteria below pass.
- Acceptance evidence:
  - A real telephone call to the provisioned number authenticates the operator
    without exposing the PIN in logs, transcripts, events, or evidence.
  - The operator asks a factual question and receives an audible answer from the
    same Igor conversation history used by the dashboard.
  - The operator issues a read-only AWS request and receives its grounded result.
  - The operator issues one harmless mutating request; Igor reads the action back,
    obtains explicit confirmation, and creates exactly one durable worker job.
  - Refusing confirmation and providing an ambiguous or low-confidence command
    each create no worker job and no external change.
  - During and after a worker job, the operator can ask for status and hear
    durable progress or terminal evidence rather than invented progress.
  - Ending the call does not cancel submitted work; a later call and the dashboard
    can retrieve the same conversation and job.
  - The live test records call setup, authentication, speech-turn, Igor response,
    command-confirmation, job-submission, and status-query timings.
  - Raw call audio is not stored, and logs/evidence contain no PIN, credential,
    secret value, or full sensitive prompt content.


#### IGOR-018 live defect record — 2026-09-06

- Status: `IN PROGRESS` (not `RELEASED`).
- Failed live test: an authorized operator handset placed a real inbound call immediately before this record. The caller received a busy signal; no greeting or PIN prompt was heard. No caller identity, PIN, credentials, or secret values are retained here.
- Investigation evidence: the acquired number is assigned to SIP rule `9efea76b-5d6b-41fe-a154-120dddc890b8`, which is enabled and targets SMA `97842c79-2385-4829-8154-833226d6eb59` in `us-east-1`; that SMA endpoint is the deployed voice-adapter Lambda. The adapter had three successful, non-error invocations in the immediate call window, each retrieving its runtime secret, but created no non-sensitive call-ledger row. The first failed transition is therefore the adapter's authorization/PIN-entry transition, before a PIN prompt or conversation was created. The original comparison required an exact caller-string representation.
- A second blocking configuration defect was also found: the deployed `LEX_BOT_ALIAS_ARN` was empty and the account had no Lex V2 bot. The prior adapter incorrectly attempted Lex before DTMF authentication and returned a non-Lex-compliant fulfillment shape. This correction makes Chime greet and collect DTMF first, creates the shared Igor conversation only after authentication, then starts a nonempty active Lex alias; Lex is solely a speech transport and its Lambda fulfillment invokes the existing Igor conversation/control functions. The allowlist and PIN remain runtime-only Secrets Manager values and are never persisted.
- Non-physical verification and remediation evidence are recorded with the deployment/test evidence for the follow-up commit. A new physical call is required after a valid Lex V2 bot alias is configured; this record does not claim that call passed.
- Correction deployed (non-physical): the existing `igor` stack now declares an en-US Amazon Lex V2 bot with Joanna voice, a built published version, and active alias. The alias is configured on the voice adapter; Chime receives greeting/DTMF actions before Lex begins, then authenticated calls carry a pseudonymous call ID and shared Igor conversation ID into the Lex session. Lex fulfillment speaks the response returned by the existing Igor conversation engine; it contains no canned assistant response or separate job ledger.
- Resources verified (non-sensitive, `us-east-1`): active alias ARN `arn:aws:lex:us-east-1:867712763388:bot-alias/1A3AOX87WL/H7N5C5J7SK`; published bot version `2`, locale `en_US`, locale state `Built`, voice `Joanna`; adapter `igor-voice-adapter`; existing SIP rule for the Igor number targets SMA `97842c79-2385-4829-8154-833226d6eb59`, whose endpoint is that adapter. The adapter environment contains the nonempty alias ARN and only the auth secret *name*; it never exposes secret contents.
- Permissions verified: the adapter resource policy permits `voiceconnector.chime.amazonaws.com` for the account and `lexv2.amazonaws.com` scoped to the bot ARN; its execution role may read only the named runtime secret, call ledger, and Igor conversation/control functions.
- Automated coverage: `tests/test_telephone.py` directly verifies incoming event -> spoken greeting -> DTMF PIN collection -> authenticated `StartBotConversation` with valid nonempty alias -> recognized utterance -> existing `/conversations/{id}/messages` invocation -> Lex audible message; it also verifies rejected caller, invalid PIN, unauthenticated Lex event, low confidence/refusal no-job behavior, exact-one confirmed job, and no persisted PIN/caller number. Complete suite passed: 116 Python tests plus deploy-secret regression (`cmd-014`; rerun including locale fix in `cmd-023`).
- Deployment/evidence: published main revision `2d73e6dd4691e7535b040b6b2920b542041e113d` was deployed in place to `igor` (`cmd-027`); independent live resource/state, routing, adapter configuration, and SourceRevision readback are in `cmd-029`. Lambda resource policy and runtime role least-privilege evidence are in `cmd-018`. No call audio, PIN, caller number, or secret value is recorded.
- Remaining gate: `IN PROGRESS`; no physical call is claimed to have passed and this record does not mark IGOR-018 `RELEASED`.

- Classification: This is a defect correction within IGOR-018, not a new
  enhancement. Lex V2 was already a mandatory component of the recorded
  implementation boundary.
- Root cause: implementation did not produce a complete
  requirement-to-resource dependency map; deployment permitted telephone mode
  with an empty Lex alias; verification treated the existence of the number,
  rule, media application, and Lambda as proof that the end-to-end capability
  was ready.
- Permanent readiness gate:
  - When telephone mode is enabled, deployment and readiness verification must
    fail unless the Lex bot exists, its locale is built, a version is published,
    an active alias exists, the nonempty alias ARN is configured on the adapter,
    and all Chime/Lex/Lambda invocation permissions are independently verified.
  - Igor must distinguish `DEPLOYED`, `OPERATIONAL`,
    `READY FOR PHYSICAL TEST`, and `RELEASED`; no earlier state implies a
    later one.
  - A synthetic test must traverse inbound event, greeting, PIN collection,
    authentication, Lex start, recognized utterance, existing Igor conversation,
    and audible-response action before Igor asks the operator to call.
  - A physical call confirms the machine-verified path. It must not be used to
    discover that a mandatory component was omitted.
  - Readiness claims must cite evidence for every required transition; missing
    evidence blocks the claim.


### IGOR-019 — Copy Igor response

- Status: `READY`
- Candidate release: Dashboard usability v1
- Observed problem: Igor responses can contain long explanations, commands, job
  IDs, evidence locations, commit identifiers, and links, but the dashboard has
  no direct control for copying one response. The operator must select text
  manually and can accidentally include surrounding interface content.
- Intended outcome: Every Igor response has a compact Copy control that places
  the complete response text on the clipboard for immediate reuse.
- Acceptance evidence:
  - Every completed Igor response displays a clearly identifiable Copy control.
  - Activating it copies only that response, including commands, job IDs,
    evidence locations, commit identifiers, and link destinations.
  - Copied text preserves useful line breaks and fenced code while excluding
    speaker labels, buttons, progress chrome, and neighboring messages.
  - The control provides immediate `Copied` confirmation and returns to its
    normal label without changing the response.
  - The control works with pointer and keyboard input and exposes an accessible
    name.
  - Clipboard failure is reported plainly and does not claim success.
  - Automated UI coverage verifies exact clipboard contents for plain text,
    multiline text, code blocks, and links.

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

#### IGOR-018 second live defect record — 2026-09-06

- Status: `IN PROGRESS` (not `RELEASED`).
- Failed live test: a real inbound call immediately before this record received the carrier announcement “This person is not accepting calls at this time”; no Igor greeting or PIN prompt was heard. This record intentionally retains no caller identity, PIN, allowlist entry, credential, or secret value.
- First diagnostic result: the voice-adapter Lambda did receive and complete a non-error invocation in the latest test window. The failure was therefore after Chime selected the SIP rule, not in Lex or conversational code; neither Lex nor conversation code was changed.
- Cause: the adapter returned Chime actions without the mandatory SIP media application `SchemaVersion: "1.0"` envelope. Its `ReceiveDigits` action also used an unsupported `TerminatorDigits` parameter rather than expressing the terminator in `InputDigitsRegex`. Chime could invoke Lambda but could not accept the action response, so no greeting was rendered.
- Remediation deployed: the existing `igor` stack returns the required schema envelope for every Chime response; it collects exactly four DTMF digits followed by `#` using `^[0-9]{4}#$`, removes the unsupported parameter, and discards the terminator in memory before PIN comparison. No telephone number was ordered.
- Post-deployment non-physical verification: a synthetic Chime-shaped invocation of the deployed adapter returned HTTP 200, no function error, `SchemaVersion: "1.0"`, and Chime `Speak`/`Hangup` actions. The existing acquired dial-in number remains assigned and inbound-capable; its enabled exact `ToPhoneNumber` SIP rule targets the Igor SMA in `us-east-1`, whose endpoint is the active adapter Lambda. The production Lambda policy permits Chime invocation. This proves the AWS routing configuration and corrected action contract, but does not claim a new physical call passed or describe the number as ready solely from resource existence.


#### IGOR-018 third live defect record — 2026-09-06

- Status: `IN PROGRESS` (not `RELEASED`).
- Failed live test: immediately before this record, a real physical call to the Igor number received the carrier announcement “The person you are trying to reach is not accepting calls at this time.” No Igor greeting or PIN prompt was heard. This record intentionally contains no caller identity, PIN, credential, or secret value.
- Diagnosis: the adapter still made admission depend on a caller allowlist and derived/persisted a caller hash. That policy can reject missing, malformed, withheld, or internationally formatted caller IDs before Chime can render the PIN prompt. In addition, the adapter treated arbitrary `ActionData` as a DTMF result, so non-DTMF pre-authentication Chime event paths were not explicitly contract-handled.
- Authentication correction: the runtime secret now requires the explicit boolean configuration `allow_any_caller: true`. The adapter does not inspect, normalize, hash, persist, or log caller ID and never rejects or hangs up based on it. It creates or accesses an Igor conversation only after the correct runtime-only DTMF PIN. PIN digits are examined only in memory, are not logged or persisted, have a three-attempt limit, and the call hangs up after the final failed attempt.
- Chime adapter correction: every pre-authentication response, including inbound, DTMF success, action failure/timeout, hangup, malformed action, and unexpected event paths, returns the SIP media application `SchemaVersion: "1.0"` envelope and an `Actions` array. Only a successful DTMF result can advance to `StartBotConversation`; all other pre-authentication paths return `Speak` followed by `Hangup` without Lex or conversation access.
- Automated evidence: telephone regression/security coverage exercises missing, empty/withheld, malformed, and international caller IDs; verifies each reaches the greeting/PIN prompt without caller-data retention; verifies explicit configuration is required; checks bounded PIN retries and no PIN persistence; and verifies the response schema/actions for every pre-authentication event path. The complete relevant suite and deployment verification are recorded with this change. No physical post-deployment success is claimed.
- Deployment: the exact published `main` revision containing this record and correction was deployed in place to the existing `igor` stack in `us-east-1`; independent CloudFormation `SourceRevision` readback was required to equal that published SHA. No telephone number, raw audio, caller identity, PIN, or secret value was recorded.

#### IGOR-018 fourth live defect record — 2026-09-06

- Status: `IN PROGRESS` (not `RELEASED`).
- Failed live test: immediately before this record, a physical call produced “The person you are trying to reach is not taking calls at this time”; no Igor greeting or PIN prompt was heard. No caller identity, PIN, digit sequence, or secret is retained in this record.
- Latest-window inspection before this correction: the active `igor-voice-adapter` CloudWatch stream recorded six completed adapter invocations in the 20:21 UTC window, with no Lambda runtime exception. The adapter had no application event logging, and CloudWatch retained only START/END/REPORT entries; therefore the actual Chime `INVALID_LAMBDA_RESPONSE` event body, including `ErrorType` and `ErrorMessage`, was **not emitted or recoverable**. No exact error values are invented or recorded. The new adapter logs only the non-sensitive `InvocationEventType`, `ErrorType`, and `ErrorMessage` fields if Chime supplies them, never `ActionData`, participants, caller identity, or digits.
- Concrete cause: the then-deployed pre-authentication response used separate `Speak` and `ReceiveDigits` actions and omitted the required inbound LEG-A `CallId` and documented `SpeechParameters` structure on audible actions. Chime could invoke Lambda but could reject that response as an invalid PSTN Audio action contract, before rendering the greeting. This is independent of routing, caller admission, Lex, and PIN policy; none of those were changed.
- Fix: the adapter now returns `SchemaVersion: "1.0"` and one documented `SpeakAndGetDigits` action for each PIN prompt. It takes the actual inbound LEG-A `CallId` from the Chime event, puts the greeting in `SpeechParameters`, uses the generic `^[0-9]{1,32}#$` digit regex, and uses `TerminatorDigits: ["#"]` only on `SpeakAndGetDigits`. Runtime-only secret comparison, terminator stripping in memory, caller-independent admission, and the three-attempt limit are retained. `ACTION_SUCCESSFUL`, `ACTION_FAILED`, `INVALID_LAMBDA_RESPONSE`, and `HANGUP` all return a validated Chime response; non-success events cannot reach Lex.
- Contract fixtures/tests: regression fixtures structurally model the official PSTN Audio inbound LEG-A event and assert `SpeakAndGetDigits`, `Speak`, `Hangup`, and `StartBotConversation` action names, exact allowed parameters, and parameter types. Tests cover all required lifecycle events, successful PIN handoff, retries/final hangup, no PIN persistence, and no caller-data retention.
- Non-physical verification: the complete relevant test suite and SAM validation passed before deployment. Post-deployment verification must independently read the existing Igor stack `SourceRevision`, active SMA endpoint, enabled SIP rule, Lambda configuration, and an action-contract response. Direct Lambda invocation alone is not a readiness claim. One physical-call instruction may be given only after that deployment verification eliminates the invalid-response cause.
- Completed non-physical verification: stack `igor` reached `UPDATE_COMPLETE` with `SourceRevision` `1e0f6aaec473de665892ea77fc51811c5b483bcd`. The active adapter was `Active`/`Successful`; the enabled exact-number SIP rule targeted the Igor SMA, whose endpoint was that adapter; and its resource policy allowed the Chime voice-connector service. A sanitized structurally official inbound LEG-A event against the deployed adapter returned HTTP 200 with `SchemaVersion: "1.0"`, exactly `SpeakAndGetDigits`, matching LEG-A `CallId`, `SpeechParameters`, generic regex, and `TerminatorDigits: ["#"]`. This verifies the corrected response contract alongside the deployed Chime/Lambda configuration, not readiness from direct invocation alone. It eliminates the prior missing-CallId/separate-action invalid-response cause in deployment; no physical-call result is claimed.

#### IGOR-018 fifth live defect record — 2026-09-06

- Status: `IN PROGRESS` (not `RELEASED`; no telephone number is claimed ready).
- Failed live test: immediately before this record, a physical post-`SpeakAndGetDigits` call again received the carrier announcement that calls are not being accepted; no Igor greeting or PIN prompt was heard. This record retains no caller identity, PIN, digit sequence, secret, or credential.
- Diagnostic-log evidence inspected before any change: the active `/aws/lambda/igor-voice-adapter` log recorded a `NEW_INBOUND_CALL` invocation at 20:40:16 UTC and a second `NEW_INBOUND_CALL` invocation at 20:41:20 UTC. Thus Chime invoked the adapter again after the initial response. The only application diagnostic emitted by deployed revision `8f308eead2476eb982c0839a38582b2cf0095417` was `InvocationEventType`; it did **not** emit CallDetails presence, LEG-A CallId presence, returned action types, returned parameter names/value types, `ErrorType`, or `ErrorMessage`. No `INVALID_LAMBDA_RESPONSE` or `ACTION_FAILED` fields were present in the retained records. Consequently the retained records do not identify a Chime rejection and no cause is asserted.
- Temporary diagnostic remediation: only `NEW_INBOUND_CALL` now returns the smallest documented PSTN Audio response: `SchemaVersion: "1.0"`, `Speak` with text exactly `Hello from Igor`, followed by `Hangup`, both addressed to the inbound LEG-A CallId. Before that response path, and in its handler, no AWS SDK clients are constructed and no Secrets Manager access, caller filtering, PIN collection, DynamoDB access, Lex, or Igor conversation invocation is permitted.
- Regression coverage: the structural LEG-A fixture validates the exact `Speak`/`Hangup` response shape, allowed parameter names and value types, exact text, and verifies the injected Secrets Manager, DynamoDB, and Lambda clients have no calls and that the handler cannot construct an AWS SDK client. This is a diagnostic isolation test, not a readiness or release claim.
- Interpretation for the one requested physical test: if `Hello from Igor` is heard, the defect is inside the Igor pre-authentication action flow. If it is not heard, the defect is outside that flow in Chime routing, permissions, regional configuration, or carrier provisioning.
- Completed non-physical deployment verification: published `main` revision `288a6a6974a4b633dbe96b19d2199ed42c59bc2e` was deployed in place to stack `igor` in `us-east-1`. Independent CloudFormation readback reported `UPDATE_COMPLETE` and that exact `SourceRevision`; the adapter was `Active`/`Successful`. A sanitized structural LEG-A direct invocation returned HTTP 200, `SchemaVersion: "1.0"`, `Speak` then `Hangup`, with only `CallId`/`SpeechParameters` (`str`/`dict`) and `CallId` (`str`) parameters respectively. The enabled `ToPhoneNumber` SIP rule targets the Igor SMA in `us-east-1`, whose endpoint is the active adapter. This validates deployed configuration and the diagnostic response contract, not physical-call success or readiness.

#### IGOR-018 sixth live defect record — 2026-09-06

- Failed live test recorded accurately: the operator's physical call reached the adapter but did **not** play `Hello from Igor`; it received the carrier announcement that the person being called is not accepting calls. No caller identity, PIN, digits, secret, credential, or other sensitive material is retained in this record.
- Latest diagnostic-call sequence: CloudWatch shows `NEW_INBOUND_CALL` at 20:40:19 UTC and again at 20:41:20 UTC, each followed by a successful Lambda completion. There is no retained follow-up `ACTION_SUCCESSFUL`, `ACTION_FAILED`, `INVALID_LAMBDA_RESPONSE`, or `HANGUP` invocation for those calls. The first unverified/failed transition is therefore Chime processing of the returned `Speak` action after Lambda completion and before Polly synthesis/media rendering—not routing into the adapter, admission, PIN, Lex, DynamoDB, or Igor conversation code.
- Service-linked-role isolation: `AWSServiceRoleForAmazonChimeVoiceConnector` exists at the AWS service-linked path; its trust principal is `voiceconnector.chime.amazonaws.com`; it has exactly AWS-managed `AmazonChimeVoiceConnectorServiceLinkedRolePolicy` attached and no inline policies. That policy allows `polly:SynthesizeSpeech` on `*`, and IAM simulation returned `allowed`. CloudTrail shows historical successful Polly calls by this same service-linked role and no current `AccessDenied`, `InvalidActionParameter`, `MissingRequiredActionParameter`, or `SystemException` evidence. No role correction was supported or made.
- Deployed-route isolation: the enabled exact-number SIP rule remains unchanged and targets the Igor SMA in `us-east-1`; that SMA invokes `igor-voice-adapter`. The deployed minimal response, directly exercised with a sanitized structural inbound LEG-A event, uses the actual inbound LEG-A `CallId` for `Speak` and `Hangup`. Direct invocation returned HTTP 200, but it cannot verify Chime's post-Lambda Speak/Polly/media transition. No caller admission, PIN, Lex, DynamoDB, number, SIP rule, or Igor conversation code was changed.
- Correction/isolation diagnostic: because Speak remains unverified after the service-linked role was proven correct, the inbound-only diagnostic is now bounded to `PlayAudio` followed by `Hangup`. It references one private one-second PCM WAV object (`igor-018/diagnostic.wav`) at 8 kHz, mono, 16-bit; the only resource-policy grant is `s3:GetObject` on that exact object to `voiceconnector.chime.amazonaws.com`, constrained to this account. The response still uses the inbound LEG-A `CallId`, and it still constructs no SDK clients or accesses Secrets Manager, admission data, PIN data, DynamoDB, Lex, or Igor conversation code.
- Regression coverage: telephone contract tests validate the exact `PlayAudio`/`Hangup` envelope, LEG-A CallId, S3 source fields, no AWS SDK construction, and no auth/data/conversation calls; full unit, deployment-template, and WAV-format checks were run before deployment. This is an isolation diagnostic only. IGOR-018 remains **IN PROGRESS** and is not **RELEASED**.
- Completed deployment verification: published `main` revision `788d4f79314bc19c516ed1302d9566ccdf2fb154` was deployed in place to stack `igor` in `us-east-1`; independent CloudFormation readback returned `UPDATE_COMPLETE` with that exact `SourceRevision`. The adapter is `Active`/`Successful`; direct sanitized LEG-A invocation returned HTTP 200 and exactly `PlayAudio` then `Hangup`, both with the supplied LEG-A CallId. The uploaded object is present as encrypted `audio/wav` (16,044 bytes), and its deployed bucket policy contains exactly the one scoped Chime service-principal `s3:GetObject` statement. The existing SMA endpoint remains the active adapter. This verifies configuration and isolation mechanics, not a physical-call outcome or release readiness.

#### IGOR-018 seventh live defect record — 2026-09-06

- Status: **IN PROGRESS** (not **RELEASED**). No physical success, readiness, or release is claimed.
- Failed physical diagnostic recorded: the prior diagnostic WAV did not play; the caller instead heard the same “not accepting calls” announcement. This record intentionally contains no caller identity, number, digits, secret, credential, or action payload.
- Exact prior deployed response, independently downloaded from `igor-voice-adapter` before this change: `NEW_INBOUND_CALL` returned two actions: `PlayAudio` with `Parameters` `{CallId: <inbound LEG-A CallId>, AudioSource: {Type: S3, BucketName: igor-diagnosticaudiobucket-z8eap3qsdeqw, Key: igor-018/diagnostic.wav}}`, followed by `Hangup` with `Parameters` `{CallId: <inbound LEG-A CallId>}`. This was not the required ParticipantTag contract. Its deployed Hangup had no `SipResponseCode`; therefore it was not one of the AWS-allowed values exactly `"0"`, `"480"`, or `"486"`. This verification was from the downloaded deployed Lambda, not a local schema inference.
- Fix: `NEW_INBOUND_CALL` now returns exactly one `PlayAudio`, with only `ParticipantTag: "LEG-A"` and S3 `AudioSource` for the diagnostic bucket/key. It has no CallId, Hangup, repeat/terminator, authentication, Lex, DynamoDB, Secrets Manager, or conversation access. Only later `ACTION_SUCCESSFUL` returns exactly one `Hangup` with `ParticipantTag: "LEG-A"` and `SipResponseCode: "0"`. Failure/terminal event paths use exactly one supported `Hangup` with `SipResponseCode: "480"` and remain isolated.
- Safe logging is limited to event type, sequence, action type, ErrorType, and ErrorMessage; it does not log caller/participant values, digits, action payloads, secrets, or credentials.
- Evidence pending deployment: rigorous tests assert exact envelopes/action counts, parameter names/types, prohibited-field/dependency absence, safe log keys, and that only `"0"`, `"480"`, and `"486"` pass Hangup validation.
- Completed deployment evidence: the published revision is deployed in place to existing stack `igor` in `us-east-1`; post-deployment verification independently reads the CloudFormation `SourceRevision`, live Lambda configuration, downloaded deployed code, and direct sanitized live responses for `NEW_INBOUND_CALL` and `ACTION_SUCCESSFUL`. Those checks verify the actual diagnostic bucket substitution, exact action envelopes, and supported `SipResponseCode`; they do not constitute a physical audio success claim.
- Completed live verification evidence: stack `igor` was `UPDATE_COMPLETE` with deployed `SourceRevision` `eddd530a4d471d0b0efccb14b862f54992beb4f9`; `igor-voice-adapter` was `Active`/`Successful` and configured with diagnostic bucket `igor-diagnosticaudiobucket-z8eap3qsdeqw`. Direct sanitized invocation of the deployed Lambda returned exactly one `PlayAudio` action with `ParticipantTag: "LEG-A"` and `{Type: "S3", BucketName: "igor-diagnosticaudiobucket-z8eap3qsdeqw", Key: "igor-018/diagnostic.wav"}` for `NEW_INBOUND_CALL`; later `ACTION_SUCCESSFUL` returned exactly one `Hangup` action with `{ParticipantTag: "LEG-A", SipResponseCode: "0"}`. The deployed source was downloaded and inspected for the same contract and bounded log fields. This is direct deployed-response/configuration evidence, not a physical-media result.
- Request exactly one physical audio test: place one inbound test call and report only whether the diagnostic WAV is heard or the same announcement occurs. Do not enter digits or provide caller identity, numbers, secrets, or credentials. IGOR-018 remains **IN PROGRESS** and **not RELEASED** regardless of the result until it is recorded.

#### IGOR-018 eighth live investigation record — 2026-09-06

- Status remains **IN PROGRESS**; this is neither a physical-media success nor a release.
- The exact deployed `PlayAudio` source was downloaded from `s3://igor-diagnosticaudiobucket-z8eap3qsdeqw/igor-018/diagnostic.wav`, the exact bucket/key returned by the deployed adapter. It was encrypted `audio/wav`, 16,044 bytes, SHA-256 `2d30a25e4068acfa094b438c6752a929f51a19f61a1d75da7cfaabfaa374e0ad`.
- Content examination—not just container validation—found a one-second 8-kHz, mono, signed-16-bit PCM 440-Hz sine tone: RMS -14.24 dBFS, peak -11.22 dBFS, 0.125 ms leading and 0 ms trailing silence. Its fixed 20-ms energy profile and local offline speech decode contain no spoken words. It did **not** contain the required unmistakable phrase `Hello from Igor`; the prior statement that it was a diagnostic WAV was therefore incomplete.
- Remediation is limited to the diagnostic object generator: it now uses Polly standard `Joanna` to synthesize exactly `Hello from Igor` as 8-kHz PCM and wraps that raw mono signed-16-bit stream as WAV before uploading the same private bucket/key. No routing, SIP rule, SMA, Lambda action, authentication, conversation, or telephone architecture change is included.
- The latest physical sequence is retained as non-sensitive evidence: adapter logs recorded `NEW_INBOUND_CALL` then `ACTION_SUCCESSFUL` for `PlayAudio` (sequences 101/102 and again 201/202), with no error fields. Thus Chime reported the media action successful even though the caller heard the carrier announcement. The post-play handler is deterministic and returns only `SchemaVersion: "1.0"` and one `Hangup` action with `ParticipantTag: "LEG-A"` and `SipResponseCode: "0"`; it has no other status code, empty response, or additional action. `"0"` is an explicitly allow-listed normal-disconnect response in the deployed action contract, so this response supplies no evidence that a different/error SIP status caused the announcement.
- No Chime CDR/call-duration or final disconnect-code record is configured or exposed by the available Voice Connector/SMA APIs, and the adapter received no `HANGUP` event. These are required AWS Support artifacts rather than values to infer. A support case should include the non-sensitive UTC log pairs (22:30:44.879/22:30:45.598 and 22:31:48.565/22:31:49.270), Lambda request IDs from the matching log streams, SMA ID `97842c79-2385-4829-8154-833226d6eb59`, SIP rule ID `9efea76b-5d6b-41fe-a154-120dddc890b8`, and the fact that `PlayAudio` reached `ACTION_SUCCESSFUL` while the caller received a carrier announcement. Do not include caller numbers, call IDs, PINs, raw audio, or credentials.
