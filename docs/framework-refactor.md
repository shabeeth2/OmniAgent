# Historical prebuilt-agent experiment (superseded)

The decision below describes the earlier sequential-only contract. The approved November 12 refactor adopts native batched HITL, concurrent independent reads, and retirement of incompatible pending runs; see [the current contract](ultra-refactor.md). The experiment remains historical evidence.

# Prebuilt agent compatibility experiment

The offline experiment in `backend/tests/test_framework_compatibility.py` uses the
installed LangChain `create_agent`, a fake framework chat model, real tool
dispatch, per-call human approval middleware, and model-limit middleware. It makes
no network or provider calls and does not open saved application databases.

## Decision

Follow-up: LangGraph's `max_concurrency=1` serializes execution in the tested
two-tool case, but per-call HITL still returns two simultaneous interrupts.
Approving the first executes it while the second remains pending. An adapter
could expose one interrupt at a time, but it must persist pending interrupt IDs,
enforce ordering, reject out-of-order decisions, and preserve restart, exact-call
validation, discovery, traces, and the existing API. This workaround has not yet
been implemented or proven to reduce overall code. See
`test_max_concurrency_serializes_execution_but_not_approval_interrupts`.

Keep the current production `BusinessAgent` graph. The prebuilt default executor
runs calls from one model response concurrently. With per-call approval enabled,
two proposed calls produce two simultaneous pending interrupts. The application
requires one ordered call and approval at a time, including restart. A prompt or
generic lock does not provide that durable ordering contract. Adding a custom
scheduler would duplicate the orchestration being removed, so the approved
adoption gate is not met.

The experiment also verifies that a thread-level model-call limit persists across
approval resume. Thus built-in limits are usable pieces, but they do not resolve
the sequential-execution incompatibility. Default per-invocation limits must not
be substituted for a budget spanning several approval resumes.

No engine migration or legacy compatibility layer is introduced because the
production engine has not changed. Existing checkpoint IDs and pending approvals
continue on the existing graph. Existing restart/approval tests remain applicable.

Baseline physical production lines (including blanks/comments) at experiment:
`agent/graph.py`: 299; `agent/runtime.py`: 93; `agent/budgets.py`: 39.
This experiment removes zero production lines and adds no production dependency.
The test records the incompatibility explicitly instead of claiming an unverified
line reduction or installing an unused alternative runtime.
