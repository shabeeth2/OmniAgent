# Ultra refactor — November 12, 2026

## Approved contract

Keep the local single-user FastAPI/Next.js application, endpoint paths, SSE events,
simulated PayPal workflows, cited retrieval, discovery, and durable request history.
Independent reads may run concurrently. Trusted read classifications do not require
approval; writes and unknown effects do. Clarification never grants approval.

Use one native LangChain batched approval interrupt per model turn. Every gated
call has a distinct call ID and an explicit decision, including identical calls.
Accept the existing whole-batch decision and per-call decision request formats;
translate call-ID decisions to framework action order. Reject missing, duplicate,
foreign, stale, and changed-configuration decisions before executing effects.

## Implementation sequence

1. Add production-agent approval regressions, then use native batched HITL and
   remove per-call matching/resume workarounds. Retain application policy for
   tool selection, validation, exact rejected calls, budgets, and redacted traces.
2. Version new runs as `langchain-batched-v1`. On startup retire incompatible
   pending approvals and questions with an explicit failure explanation, sync
   request history, and clear pending payloads. Keep messages, traces, databases,
   and checkpoint files. Never execute or replay retired calls. Preserve compatible
   current-engine pending runs and fail interrupted active calls as before.
3. Port useful legacy tests to the production agent, remove the legacy graph and
   router adapter, and retain engine-version columns as historical metadata.
4. Derive active messages from the session collection; share updates and saved-state
   reconciliation across send/approval/clarification. Add an explicit retry for
   failed pending-status restoration and ignore stale conversation responses.
   Never automatically replay an uncertain submission.
5. Reduce composer/sidebar to their active UI. Preserve appearance, search,
   keyboard navigation, responsive behavior, and accessibility. Remove preview
   controls, fake integrations, autoplay, and unused animations. Prune unreachable
   component exports/wrappers and their dependencies, retaining used markdown,
   diagrams, dialogs, and scrolling. Merge CSS using currently effective values.
6. Source the executable catalog from the chat agent's published registry snapshot,
   include controls, preserve metadata-only descriptors, and avoid duplicate rows.
   Remove unused backend schemas/imports and redundant exception/size checks while
   preserving the canonical network transport protections. Align launcher and
   Python metadata with supported runtime without unrelated package upgrades.
7. Update current instructions/documentation, label superseded experiment findings
   historical, and record measured reductions and executed validation separately.

## Acceptance checks

- Real production agent: multi-call approvals with mixed decisions, identical
  arguments/distinct IDs, rejection retry prevention, configuration changes,
  concurrent reads, unknown effects, budgets, cancellation, traces, and restart.
- Temporary databases: retirement is idempotent, retains history, clears pending
  cards, and permits a new turn without replay. Current-engine pauses still resume.
- Frontend: chunked SSE/DONE handling, batch decision serialization, clarification
  navigation/timers, restoration retry, stale responses, and canonical message state.
- Existing business tests retain pagination, separate-currency totals, simulated
  invoice idempotency, discovery, and cited retrieval coverage.
- Full offline backend suite; frontend tests/lint/build; served stylesheet check;
  desktop/mobile browser verification using the offline fixture where feasible.

## Boundaries

Preserve existing uncommitted changes and staging. Do not modify saved databases,
read credentials, run live paid providers/evaluations, or delete reference assets.
No new orchestration framework, infrastructure, redesign, or speculative abstraction.
No suppressed checks or removed behavioral coverage to obtain passing tests.

## Baseline during planning

Frontend regression scripts and ESLint passed. Webpack compilation and TypeScript
passed; prerender failed with an EPERM directory-creation error. Backend baseline
did not finish before it was stopped; no passing baseline count is claimed.
Earlier validation reports describe earlier snapshots, not this refactor.

## Completed changes and measured result

Implemented the sequence above. Policy now runs before native batched HITL;
this fixes approval-before-validation and rejected-call retry behavior instead
of introducing a custom replay/deduplication layer. Legacy graph/resume dispatch
is removed. Compatible pauses resume; old-engine pending requests retire once,
retain their history, and allow a fresh turn. Shared redaction covers approvals
and trace callbacks. Context exhaustion reports a budget-exhausted outcome.

Session messages are canonical; saved-state recovery uses GET requests only.
Repeated active-session selection, explicit status retry, stale response rejection,
and mobile drawer dismissal are covered. Hidden preview controls, unused component
exports/wrappers and their packages are removed. Catalog uses the published agent
snapshot and includes both controls without duplicated enabled-connection rows.
Python metadata and regenerated lock target 3.13; supported package versions were
not upgraded. Launcher aliases use the same loopback/Webpack path.

Counts use physical lines, including blanks/comments, measured with PowerShell
`Get-Content` before implementation and after completion. Tests, scripts, styles,
configuration, documentation, catalogs and lockfiles are excluded from source counts.

| Production source scope | Before | After | Reduction |
| --- | ---: | ---: | ---: |
| Backend Python modules | 2,683 lines / 28 files | 2,307 lines / 27 files | 376 lines / 1 file |
| Frontend app/components/lib TS(X) | 3,843 lines / 30 files | 1,727 lines / 20 files | 2,116 lines / 10 files |
| Combined source | 6,526 lines / 58 files | 4,034 lines / 47 files | 2,492 lines / 11 files |
| Direct frontend runtime dependencies | 24 | 15 | 9 |

Removed packages: Radix collapsible, dropdown-menu, hover-card, select, separator,
tooltip; `ai`, `cmdk`, and `glimm`. Used dialogs, markdown/code/math/diagram plugins,
and scrolling remain. Lockfiles were regenerated through package managers.
The duplicate API response-size check remains: the removal experiment failed the
oversized pre-buffered response case, so the second guard is still necessary.

## Executed final validation

- Full offline backend suite: **93 tests passed in 48.591 seconds** using
  `.venv/Scripts/python.exe -u -m unittest discover -s tests` from `fastapi`.
- Frontend `npm test` passed, including behavioral page recovery tests;
  `npx tsc --noEmit`, ESLint and Webpack production build passed.
- `npm run check:styles -- http://127.0.0.1:3000` passed against the production server.
- PowerShell launcher syntax parsed successfully; installer/launcher was not executed.
- Browser: restored cited knowledge answer; same active-conversation selection;
  all three sales pages yielding USD 150.00 and EUR 20.00 separately; native two-call
  batch card restored after page reload; approve-first/reject-second created one
  simulated draft without sending; three-question clarification resumed with the
  submitted choices/custom answer; catalog showed system_search and ask_user.
- Responsive check: 390×844 viewport, document width 390 without horizontal overflow,
  visible/enabled composer, and selecting the current mobile conversation closed
  navigation. Desktop view and mobile screenshots were inspected. No browser
  console errors were captured.
- Production and fixture servers were stopped after verification. Browser fixture
  uses scripted responses, hash embeddings and temporary databases; it is not live
  model-quality evidence. No paid/provider evaluations or external effects ran.
- Git whitespace checks passed in both repositories. Existing staging was preserved;
  no commits were created. No tracked saved-database changes appeared. An untracked
  tool-embedding cache appeared during the session; its provenance could not be
  established from test call sites, so it was left untouched.
