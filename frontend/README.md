# Frontend

This Next.js App Router application provides the chat, approval, clarification, and tool registry UI. Its development and production build scripts use Webpack.

From `frontend/`, install dependencies and start the UI:

```powershell
npm ci
npm run dev
```

The UI defaults to the backend at `http://localhost:8000`. Set `NEXT_PUBLIC_FASTAPI_URL` to change it. For application setup and architecture, see the [repository README](../README.md) and [backend guide](../backend/README.md).

Run `npm test`, `npm run lint`, `npx tsc --noEmit`, and `npm run build` for offline checks. `npm run check:styles` requires a running frontend.
