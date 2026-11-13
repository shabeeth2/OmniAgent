# Frontend

This Next.js App Router application provides the chat, approval, clarification, and tool registry UI. Its development and production build scripts use Webpack.

## Run the complete app

On Windows, run `.\run-app.bat` from the repository root. It checks/installs prerequisites and dependencies, then launches both local servers. Open [localhost:3000](http://localhost:3000).

Use **Configure LLM**, directly above the sidebar user profile, to set chat and embedding models, endpoints, API keys, and the context budget. Settings are saved to `backend/.env`; saved keys are never returned or stored in browser storage. Leave an API-key field blank to keep its existing value. Restart the backend to apply saved changes. The UI can open before providers are configured. See the [backend setup](../backend/README.md) for generic `LLM_*` and `EMBEDDING_*` variables and protocol requirements.

## Frontend only

From `frontend/`, install dependencies and start the UI:

```powershell
npm ci
npm run dev
```

The UI defaults to the backend at `http://localhost:8000`. Set `NEXT_PUBLIC_FASTAPI_URL` to change it. For application setup and architecture, see the [repository README](../README.md) and [backend guide](../backend/README.md).

Run `npm test`, `npm run lint`, `npx tsc --noEmit`, and `npm run build` for offline checks. `npm run check:styles` requires a running frontend.

## Tool registry and approvals

Open the sidebar's Tool registry to save, edit, test, remove, and explicitly enable MCP or GET API tools. Saving is distinct from testing and activation. API test inputs are generated from the scalar query schema.

The chat starters exercise simulated invoice drafts, paginated completed sales totals by currency, and cited knowledge retrieval. Simulated invoice approvals send no email or payment. Enabled external connections can make real calls. Pending approval cards and ordered tool traces restore when reopening a conversation; traces show discovery, execution, decisions, and catalog versions when provided by the backend.
