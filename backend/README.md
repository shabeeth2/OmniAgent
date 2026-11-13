# Agent backend

Local single-user FastAPI/LangGraph demonstration of tool discovery, dependency-aware execution, cited knowledge retrieval and durable batched approvals. See the [architecture proposal](../docs/scalable-agentic-system.md) for workflows, alternatives, scaling limits and acceptance evidence. PayPal tools are simulations: no PayPal connection or real invoice delivery is implemented. Enabled external API/MCP tools can execute real calls. Writes and unknown effects require approval; trusted read classifications do not.

## Setup

For the whole app on Windows, run `.\run-app.bat` from the repository root. It installs/checks prerequisites and dependencies and launches both servers. Open [localhost:3000](http://localhost:3000), then click **Configure LLM** above the sidebar profile to save chat and embedding settings. Stop the existing servers and restart after saving. Keep one backend process on loopback.

The backend can start without provider settings so the configuration UI and saved history remain available; chat returns 503 until settings are supplied and the backend is restarted. Saving settings does not call a provider. Startup with configured providers builds indexes and can incur charges.

### Manual backend setup

Use Python 3.13, pinned in `.python-version`, for the local Docling dependency stack. `pyproject.toml` requires `>=3.13,<3.14`.

From `backend/`:

```powershell
uv sync --locked --python 3.13
```

Alternatively, create `.env` in `backend/` with your provider settings:

```dotenv
LLM_MODEL=your-tool-calling-chat-model
LLM_API_KEY=your-chat-provider-key
# Optional: an OpenAI-compatible chat endpoint
# LLM_BASE_URL=https://your-provider.example/v1
EMBEDDING_API_KEY=your-embedding-provider-key
EMBEDDING_MODEL=jina-embeddings-v5-omni-small
EMBEDDING_BASE_URL=https://api.jina.ai/v1/embeddings
# Optional serialized character budget, including schemas; not tokens
CONTEXT_BUDGET=64000
```

Chat and embeddings are independent. Chat accepts an OpenAI-compatible endpoint; embeddings require the Jina-compatible API format with 1024 dimensions. `LLM_API_KEY` is for chat, not embeddings. The generic names do not change those protocol requirements. Existing `AGENT_MODEL`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `JINA_API_KEY`, `JINA_EMBEDDING_MODEL`, and `JINA_BASE_URL` remain supported as legacy aliases. Startup validates settings, ingests `sample_docs`, and builds the tool index when configured. Document text, tool descriptions and discovery queries go to the embedding provider; chat/tool results go to the chat provider. Provider usage can incur charges. Imports alone make no provider calls.

```powershell
uv run --python 3.13 uvicorn agent_backend.main:app --reload --host 127.0.0.1 --port 8000
```

In another terminal, from `frontend/`, run `npm install` then `npm run dev`. Its dev/build scripts use **Webpack**. The frontend defaults to `http://localhost:8000`; override with `NEXT_PUBLIC_FASTAPI_URL`. CORS allows localhost and 127.0.0.1 on port 3000. Keep this unauthenticated application on loopback, with one backend process.

## Capabilities and limits

The model receives `system_search`, the always-available `retrieve_knowledge` specialist, and only request-selected business schemas. `system_search(mode="capabilities", query=...)` returns up to five ranked descriptors with availability/version. `mode="status"` reads up to five previous requests and twenty tool previews per request in the current conversation. Status query text does not currently filter the history; this is not arbitrary server-log search.

The official catalog contains 72 **metadata-only** operation descriptors from six PayPal specifications at revision `90e8041ffe02d80c452d2b476bedd59a8d219bdc`, with source/schema references and hashes. They cannot execute. Local demo handlers cover create/send invoice, transaction pages, merchant-user-to-payer mapping and dispute pages, alongside fictional customer/outstanding-invoice tools. Simulated invoice writes require separate approvals for create and send. Ask for recipient email and explicit currency; a dollar symbol is ambiguous. October 2026 gross `COMPLETED SALE` totals are USD 150.00 and EUR 20.00, separately. Outstanding invoice balances are a different metric: USD 125.50 and EUR 20.00. Relative dates use Asia/Calcutta; ask for October 2026 to explore fixed fixtures.

Requests allow three discovery calls, twelve model calls, twenty tool-call attempts and 45 seconds active time. Approval waiting is excluded. Up to fifteen selected tools accumulate. Context is bounded by serialized characters; old whole turns may be omitted from model input while saved messages remain intact. Results beyond 12,000 characters are marked incomplete/truncated. Fetch smaller pages or narrow queries before claiming totals. Conservative request status records failures/rejections even when later model text sounds successful; traces expose the individual steps.

## API and SSE

| Endpoint | Purpose |
| --- | --- |
| `POST /api/chat` | `{ "message": "...", "conversation_id": 1 }`; omit ID for a new conversation |
| `GET /api/settings/llm` | Read model, endpoint, embedding and context settings, plus API-key presence flags; never returns saved keys |
| `PUT /api/settings/llm` | Save local provider settings; blank/omitted replacement keys preserve existing keys; restart backend to apply |
| `GET /api/conversations` | List saved conversations |
| `GET /api/conversations/{id}` | Messages and saved ordered tool traces |
| `DELETE /api/conversations/{id}` | Delete conversation |
| `GET /api/conversations/{id}/pending-approval` | Restore pending approval card |
| `POST /api/conversations/{id}/approvals/{approval_id}` | Whole-batch `{ "decision": "approve" }`/`reject`, or `{ "decisions": [{ "tool_call_id": "...", "decision": "approve" }] }` covering every pending ID exactly once; returns SSE |
| `GET /api/conversations/{id}/pending-clarification` | Restore pending questions |
| `POST /api/conversations/{id}/clarifications/{clarification_id}` | Submit `{ "answers": [...] }`; returns SSE; answers never authorize effects |
| `GET /api/tool-registry/catalog` | Executable tool summaries plus metadata-only catalog descriptors |
| `GET /api/tool-registry` | Configurations with `has_api_key`, never saved credentials |
| `POST /api/tool-registry` | Save a connection |
| `PATCH/DELETE /api/tool-registry/{id}` | Edit/delete configuration |
| `POST /api/tool-registry/{id}/test` | Test with `{ "arguments": {} }` |

Chat/resume responses are `text/event-stream`, ending `data: [DONE]\n\n`. Content events contain `{"content":"..."}`. Trace events contain `{"trace":{...}}`; update rows by stable trace ID across approval/resume. Approval pauses emit `{"approval_required":{...}}` followed by DONE. Stale/concurrent decisions and new messages on active/pending conversations return 409. Traces show execution activity, not private model reasoning.

The settings payload uses `llm_model`, `llm_base_url`, `context_budget`, `embedding_model`, and `embedding_base_url`. Send optional `llm_api_key` and `embedding_api_key` only to replace keys. Responses use `llm_api_key_configured` and `embedding_api_key_configured` flags and `restart_required` to indicate whether a restart is needed. Settings persist in the local plaintext `.env`; protect it with OS permissions and never commit it.

## Saved state and restarts

| Local file | Contents |
| --- | --- |
| `data/app.db` | Conversations, messages, current run locks, append-only request history and traces |
| `data/agent-checkpoints.db` | Durable LangGraph execution/approval state |
| `data/paypal-demo.db` | Simulated invoices and seeded business records |
| `data/tool-embeddings.db` | Content-addressed description embeddings |
| `data/tool-registry.json` | Registry and plaintext credentials; gitignored |

Startup creates tables, adds the trace catalog-version column if missing and backfills available historical current-run records. It cannot recover historical runs that were never saved separately. Pending approvals survive restarts; active interrupted executions are failed and never replayed automatically. Registry changes invalidate pending approval. Checkpointing cannot guarantee exactly-once effects when a process crashes during an external request; reconcile before retrying.

Tool embeddings use a `jina-v1` cache identity containing model, endpoint, and dimensions; cache keys also include description content. Jina uses `retrieval.passage` for descriptions and `retrieval.query` for searches. Old SQLite cache entries remain intact and are not mixed with the current provider identity. Cache misses and index writes are batched. Restart rebuilds the process-local index from cached vectors; new/changed descriptions embed again. Query embeddings are not persisted. The knowledge index is process-local and re-ingested at startup, without the tool-description cache. Rebuild knowledge after changing embedding models; never mix incompatible vectors. Protect all data files with OS permissions. Redacted previews are not a general personal-data scrubber.

## Knowledge retrieval

Docling structurally chunks local `.md`, `.txt` and `.pdf` files and retains source/available PDF-page citations. PDF conversion may download model assets on first use. The default corpus is `sample_docs`, containing fictional policies. There is no upload endpoint or background refresh. An empty corpus returns an explicit unavailable result rather than fabricated knowledge.

```powershell
uv run --python 3.13 python -m agent_backend.ingest --docs sample_docs --query "How quickly does support respond?"
```

The CLI builds its own store and exits; it does not populate the running server. For direct usage, pass the same store from `ingest(...)` into `create_retrieval_tool(store)`. Custom LangChain `Embeddings` plus matching dimensions can replace Jina in tests/ingestion.

## External connections and approvals

Save an MCP/API connection in Tool registry, test it, then enable individual discovered tools. Saving/testing does not activate tools. MCP tests discover definitions without executing them; API tests send the configured GET request, so test explicitly against a safe target. API schemas support string, boolean, integer and number query fields. Other HTTP methods can be saved but cannot be tested/enabled. Configuration changes clear tests/activation; a blank replacement credential retains the existing one.

Every executable tool declares trusted origin metadata. Simulated writes and external writes/unknown effects interrupt before execution. API GET tools and MCP tools explicitly classified locally as read are approval-free; independent reads may run concurrently. Server read-only hints alone never grant a read classification. Local reads, model calls and embedding calls do not require approval. LangChain native batched middleware presents all gated calls in a model turn together; each call requires an explicit approve/reject choice. Dependent calls wait for earlier tool results. Decisions authorize only the exact stored call. New requests capture immutable registry snapshots; background rebuilding serves the last published snapshot, while approval resume waits for fresh configuration and rejects incompatible changes.

Adapters enforce a ten-second request limit, 1 MB response limit, no redirects and no ambient proxies. HTTPS is required except explicit loopback HTTP; private/link-local/reserved/metadata destinations are blocked. These controls do not replace authentication, authorization or reviewing an MCP tool's advertised effects. The application remains a local single-user demonstration, not a shared deployment.

## Verification

Offline tests use isolated/in-memory stores and fake providers; they do not need API credentials or mutate saved chats:

```powershell
uv run --python 3.13 python -m unittest discover -s tests
```

The final ultra-refactor offline suite passed 93 tests; see [the detailed results](../docs/ultra-refactor.md#executed-final-validation). See [validation](../docs/validation.md). The offline hash discovery benchmark reports 95% recall@5 on twenty labeled queries at each of 50/100/500/1000 descriptors, using overlapping synthetic distractors. This is a routing smoke test, not semantic-model or production performance evidence. See `scripts/evaluation.py` and the architecture proposal.

The paid harness is opt-in and has not been run for this change. Its live discovery path still requests 1536 dimensions; align it with the current 1024-dimensional runtime before evaluation:

```powershell
uv run --python 3.13 python scripts/evaluation.py --mode discovery
uv run --python 3.13 python scripts/evaluation.py --mode tasks
```

The default `--mode offline` makes no provider calls. The 95% retrieval target is a project assumption; all ten live task checks must pass their programmatic factual and trace assertions. No live semantic-quality or task-completion result is claimed. For isolated browser testing, `python scripts/browser_demo.py` runs scripted responses against temporary stores; stop the normal backend first.


## Runtime retirement

New requests use `langchain-batched-v1`. Startup fails incompatible old-engine pending approvals/questions with an explicit retirement explanation, clears their pending cards, and retains conversation, request and trace history. No retired call is replayed. Current-engine pending requests retain their checkpoints across restart. Historical engine-version columns and checkpoint files remain intact. See [the refactor contract](../docs/ultra-refactor.md).
