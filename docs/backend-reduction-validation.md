> Historical November 11 results; not validation of the November 12 ultra refactor. See [the current contract](ultra-refactor.md).

# Backend dependency refactor — November 11, 2026

## Outcome

Replaced the handwritten Gemini HTTP adapter with `langchain-google-genai` 4.4.3
(locked), removed the unused `langchain-anthropic` direct dependency, and batched
knowledge/tool index writes and unique embedding-cache misses. Query embeddings
remain uncached. New integration/task cache identities preserve old rows without
mixing embedding semantics. The first startup with the new identity requires new
provider embeddings and may incur charges; no live calls were made for validation.

The real `create_agent` experiment failed the ordered-execution adoption gate:
its default executor runs tool batches concurrently and per-call approval exposes
multiple interrupts simultaneously. See [experiment](framework-refactor.md).
The production graph and checkpoint engine remain unchanged; no legacy engine
migration or temporary compatibility layer is necessary.

## Size and dependencies

Nonblank source lines measured using PowerShell `Measure-Object -Line`, including
comments, for all Python files directly in each subsystem directory:

| Subsystem | Before | After | Difference |
| --- | ---: | ---: | ---: |
| Agent | 724 | 724 | 0 |
| Tools | 446 | 438 | -8 |
| Routers | 413 | 413 | 0 |
| Ingestion module | 59 | 60 | +1 |

Net production reduction across these locations: **7 nonblank lines**.

Direct backend dependencies: 12 before and after. One official integration replaces
one unused provider integration; transitive package changes are recorded in uv.lock.
Tests and reports are excluded from production-line measurements. No large graph
reduction is claimed. SQLite cache, guarded network transport, discovery policy,
character/result budgets, redaction, SQLAlchemy history and sequential approval
orchestration remain because they enforce application contracts not supplied
equivalently by the tested replacement.

## Executed validation

- Full offline backend suite: **72 tests passed**, 34.525 seconds; temporary/in-memory stores and fake providers only.
- Frontend regression tests and ESLint passed.
- Webpack production build, including TypeScript, passed.
- Generated stylesheet check passed against a temporary loopback production frontend.
- One non-failing SQLite ResourceWarning was emitted by the backend suite.

No saved application databases were used to test changes. No live embedding/chat
quality, PDF conversion, paid evaluation, or external effect was evaluated.
