# Scalable agent demo implementation

Approved scope: local single-user FastAPI/LangGraph/SQLite + Next.js demo; simulated
PayPal operations only. Preserve existing records and external connection settings.

Implement in order: baseline; knowledge and system specialist tools; durable request
history; simulated invoice/sales/dispute workflows; cached hybrid discovery;
MCP definition checks and bounded context; evaluation and architecture submission.

Verification: offline unittest suite, frontend regression/lint/type/build, browser
verification where available, offline catalog benchmark. Paid model/embedding
evaluation is opt-in and must be reported separately from deterministic evidence.

Defaults: 3 discovery calls, 12 model calls, 20 executions, 45 active seconds,
64,000 serialized input characters, 12,000 output-preview characters, 5 candidates
per discovery, 15 selected tools. Recall@5 target 95% is a project assumption.

No live PayPal, multiuser hosting, authentication or distributed workers.
Backend is not a Git checkout; frontend already contains user changes. Do not
overwrite or commit unrelated work. Tasks are tracked in todo.md.
