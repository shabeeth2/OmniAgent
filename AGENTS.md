# agent-tool-scale Workspace

Local single-user demo: FastAPI + LangGraph agent and a Next.js chat/approval UI. Read [architecture and acceptance evidence](docs/scalable-agentic-system.md) and [backend setup](backend/README.md). PayPal actions are simulated; official catalog descriptors are metadata-only. Enabled external MCP/API tools can make real calls; trusted read classifications are approval-free, while writes and unknown effects require approval.

## Projects and commands

- `backend/`: uv project; supported runtime/pin **Python 3.13** (Docling dependency stack). From that directory: `uv sync --locked --python 3.13`; `uv run --python 3.13 uvicorn agent_backend.main:app --reload --host 127.0.0.1 --port 8000`.
- `frontend/`: Next.js 16.4.6 App Router, Tailwind v4 and AI Elements. Run `npm install`, `npm run dev`. Dev/build scripts use **Webpack** (Turbopack not verified). Checks: `npm run lint`, `npm test`, `npm run check:styles`, `npm run build`. Note: `next dev` auto-adds a `BEGIN...END` agent-rules block in `frontend/AGENTS.md`; read `node_modules/next/dist/docs/` before writing code — APIs may differ from training data.
- `run_app.cmd`: convenience launcher; use separate terminals if launcher shell handling fails.

Keep one backend process bound to loopback. There is no application authentication or multi-tenant authorization. Do not start additional workers as a scaling shortcut. Do not expose saved credentials or run paid/provider or external write evaluations without task authorization.

## Implementation map

- `backend/src/agent_backend/main.py`: lifespan, additive migration, checkpoint saver, interrupted-run recovery, loopback CORS.
- `agent/runtime.py`: independent chat/Gemini settings, startup knowledge ingestion, registry snapshot publication.
- `agent/graph.py`: LangChain create_agent with policy, native batched approvals, and model-limit middleware; exact-call approval and schema/selection gates.
- `agent/discovery.py`: hybrid top-five retrieval and metadata catalog; `utils/`: shared budget, embedding-cache, history, and trace helpers. `scripts/evaluation.py` contains offline and opt-in evaluation tooling.
- `catalog/paypal-v1.json`: 72 official, provenance-backed **nonexecutable** descriptors; local handlers use separate schemas.
- `tools/paypal_demo.py`: simulated draft/send, transaction pagination, user mapping and dispute pagination.
- `tools/rag.py`, `ingest.py`: separate cited knowledge tool and Docling ingestion.
- `utils/history.py`, `utils/traces.py`, `routers/chat.py`: durable prior-request status, trace previews and SSE.
- `frontend/app/page.tsx`, `components/PromptBar.tsx`, `components/SidebarNav.tsx`, `lib/chat.ts`: chat UI and manual fetch/ReadableStream SSE parser.
- `frontend/app/globals.css`: Tailwind v4 `@theme inline` tokens; no Tailwind config file. Read installed `node_modules/next/dist/docs/` before assuming older Next APIs.

## Settings and state

Backend `.env`: required `AGENT_MODEL`, `OPENAI_API_KEY`, `JINA_API_KEY`, `JINA_EMBEDDING_MODEL`, `JINA_BASE_URL`; optional `OPENAI_BASE_URL`, `CONTEXT_BUDGET`. Chat uses the OpenAI-compatible endpoint; knowledge and tool embeddings use Jina with 1024 dimensions. Frontend `NEXT_PUBLIC_FASTAPI_URL` defaults to `http://localhost:8000`.

`backend/data/`: `app.db` conversations/requests/traces, `agent-checkpoints.db` durable approvals, `paypal-demo.db` simulated records, `tool-embeddings.db` cached descriptions, and `tool-registry.json` plaintext local credentials. Preserve saved state. Knowledge vectors remain process-local and re-ingest at startup. Changing embedding identity/dimensions requires rebuilding compatible knowledge vectors. Startup/provider calls may incur charges; import does not call providers.

## Contract and verification

`POST /api/chat`: `{ "message": "...", "conversation_id": 1 }`, optional ID. SSE emits content, trace and approval_required objects, ending `data: [DONE]\n\n`. Resume via `POST /api/conversations/{id}/approvals/{approval_id}` with `{"decision":"approve"}` or `reject`, or `{ "decisions": [{ "tool_call_id": "...", "decision": "approve" }] }` covering every pending call exactly once. Clarifications resume separately and never authorize effects. Pending cards restore through `GET /api/conversations/{id}/pending-approval`. Full endpoint details are in the backend README.

Run offline backend checks from `backend/`: `uv run --python 3.13 python -m unittest discover -s tests`. Tests use temporary/in-memory stores and fake providers; do not modify saved databases to validate a change. Offline ingest CLI: `uv run --python 3.13 python -m agent_backend.ingest --docs sample_docs --query "..."` (builds its own store; does not populate the running server). Live evaluation is opt-in and paid: `uv run --python 3.13 python scripts/evaluation.py --mode discovery|tasks`. Hash-based discovery benchmarks are smoke evidence, not live semantic-quality proof. Final test counts belong in validation reports after checks finish; do not infer success from the existence of tests.

Follow every pagination cursor before claiming complete results. Completed SALE gross totals are not outstanding invoice totals. Keep currencies separate; never invent a recipient, currency or payer mapping. Independent reads may run concurrently. Trusted read classifications are approval-free; writes and unknown effects require explicit decisions in one batch card per model turn. Compatible pending approvals and clarifications survive restart; incompatible old-engine pauses are retired with history retained. Active interrupted calls are failed, and external effects must not be automatically retried after an uncertain crash.
