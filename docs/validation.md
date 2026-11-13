> Current ultra-refactor results: [93 backend tests, frontend/build/style/browser checks and measured reductions](ultra-refactor.md#executed-final-validation). The earlier snapshot below is retained as historical evidence.

# Validation — November 12, 2026

The local demo implementation is complete within the approved simulation scope. Live model quality and production scale are unverified.

## Executed checks

- Backend: final full offline unittest suite passed **89 tests** in 45.063 seconds. Tests use fake providers and temporary/in-memory stores. Approval and clarification resumes were verified across checkpoint restarts, including exact-call decisions, rejection traces and active-budget persistence.
- Frontend: regression tests, ESLint, TypeScript, Webpack production build, and generated stylesheet checks passed.
- Browser: production frontend against `backend/scripts/browser_demo.py`, with scripted responses and temporary databases. Verified cited support retrieval; three-page sales totals (USD 150.00, EUR 20.00); draft/send approval; restored pending send after page reload; successful simulated sending; rejection; previous-request status; mapped and paginated open disputes D1/D3. This checks UI and orchestration, not live model decisions.
- Offline discovery: [measured JSON](evaluation-results.json), 20 labeled queries at each of 50, 100, 500 and 1,000 descriptors. Recall@5 was 95% at each size. Latency and embedding/index costs are included. Synthetic catalogs and hash vectors are smoke evidence, not production semantic-quality evidence.

## Limits and remaining verification

- Paid live discovery and ten live agent scenarios were not run. Provider credentials remain external configuration.
- Unsupported-policy honesty, ambiguous natural-language routing and arithmetic by a live model require those opt-in evaluations; offline scripted cases do not establish general model reliability.
- All PayPal actions are simulated. Only representative handlers execute; the 72 official catalog descriptors are metadata only.
- SQLite, local registry credentials and process-local indexes target one local user/worker. Shared hosting, authentication, real PayPal writes and distributed workers remain future work.
- Turbopack remains outside the verified path; development and production build default to Webpack.
- One non-failing SQLite ResourceWarning appeared during the full test run. No saved application databases were used for validation.

The [architecture and FR/AC evidence matrix](scalable-agentic-system.md) separates implemented behavior, measured evidence and proposed migration work. Temporary verification servers were stopped after browser checks.
