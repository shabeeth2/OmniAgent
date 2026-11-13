import { test, expect, type Page } from "@playwright/test";

type Message = { id: number; role: "user" | "assistant"; content: string; traces?: unknown[]; ui_surfaces?: unknown[] };
type Fixture = { messages?: Message[]; approval?: unknown; clarification?: unknown };

const modelSettings = {
  llm_model: "gpt-4.1-mini", llm_base_url: "https://api.example.test/v1", context_budget: 64000,
  embedding_model: "jina-embeddings-v3", embedding_base_url: "https://embeddings.example.test/v1/embeddings",
  llm_api_key_configured: true, embedding_api_key_configured: true, restart_required: false, environment_overrides: [],
};

const catalog = [
  { name: "system_search", description: "Find relevant tools from the catalog.", origin: "system", executable: true, service: "agent", version: "1" },
  { name: "ask_user", description: "Ask for required missing details.", origin: "system", executable: true, service: "agent", version: "1" },
  { name: "retrieve_knowledge", description: "Search local knowledge and return cited passages.", origin: "system", executable: true, service: "knowledge", version: "1" },
  { name: "present_ui", description: "Display validated, read-only tables, cards, and charts.", origin: "system", executable: true, service: "agent", version: "1" },
  { name: "paypal_list_transactions", description: "List simulated transactions with pagination.", origin: "system", executable: true, service: "paypal", version: "v1" },
];
const connections = [{
  id: "fixture-mcp", name: "Research MCP", kind: "mcp", url: "https://research.example.test/mcp",
  description: "Read-only access to team runbooks and documentation.", auth_scheme: "bearer", auth_header: "Authorization", has_api_key: true,
  method: "GET", input_schema: { type: "object", properties: { query: { type: "string", description: "Search phrase" } }, required: ["query"], additionalProperties: false },
  status: "passed", tested_at: "2026-11-10T12:00:00Z", error: null,
  tools: [{ name: "search_runbooks", description: "Search team documentation.", input_schema: { type: "object", properties: { query: { type: "string" } }, required: ["query"] } }],
  enabled_tools: ["search_runbooks"], tool_effects: { search_runbooks: "read" },
}];

const conversation = (messages: Message[]) => ({ id: 1, title: "Review October sales", messages });

async function installFixture(page: Page, fixture: Fixture = {}) {
  const messages = fixture.messages ?? [
    { id: 1, role: "user" as const, content: "Find the deployment runbook and summarize the key steps." },
    { id: 2, role: "assistant" as const, content: "The runbook recommends checking service health, reviewing recent deployments, and validating rollback readiness.", traces: [
      { id: "trace-1", call_id: "call-1", tool_name: "retrieve_knowledge", status: "completed", arguments: '{"query":"deployment runbook"}', result: "Deployment Runbook · Check service health before and after rollout.", duration_ms: 820, catalog_version: "local-1" },
    ] },
  ];
  const saved = conversation(messages);
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/conversations") return route.fulfill({ json: [saved] });
    if (path === "/api/conversations/1") return route.fulfill({ json: saved });
    if (path === "/api/conversations/1/pending-approval") return route.fulfill({ json: fixture.approval ?? null });
    if (path === "/api/conversations/1/pending-clarification") return route.fulfill({ json: fixture.clarification ?? null });
    if (path === "/api/settings/llm") return route.fulfill({ json: modelSettings });
    if (path === "/api/tool-registry") return route.fulfill({ json: connections });
    if (path === "/api/tool-registry/catalog") return route.fulfill({ json: catalog });
    return route.fulfill({ status: 404, json: {} });
  });
}

async function openConversation(page: Page, viewportWidth = 1280, expectedAssistantText = "The runbook recommends checking service health") {
  await page.goto("/");
  if (viewportWidth < 768) await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("button", { name: "Review October sales", exact: true }).click();
  await expect(page.getByText(expectedAssistantText, { exact: false })).toBeVisible();
}

test("workspace home and starter prompts", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await installFixture(page, { messages: [] });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "A conversation to work from" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Create a PayPal invoice/ })).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("workspace-home.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Open navigation" }).click();
  await expect(page.getByRole("button", { name: "Tool registry" })).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("mobile-navigation.png"), fullPage: true });
});

test("saved conversation and expandable tool trace", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 1200 });
  await installFixture(page);
  await openConversation(page);
  await page.getByRole("button", { name: /1 tool call/ }).click();
  await page.getByRole("button", { name: /retrieve_knowledge/ }).click();
  await expect(page.getByText("Deployment Runbook · Check service health before and after rollout.")).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("saved-conversation-trace.png"), fullPage: true });
});

test("restored batch approval review", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 1100 });
  await installFixture(page, {
    messages: [
      { id: 1, role: "user", content: "Create and send a simulated invoice for USD 50." },
      { id: 2, role: "assistant", content: "Review these simulated invoice actions before they run.", traces: [
        { id: "approve-1", call_id: "create-1", tool_name: "paypal_create_invoice", status: "awaiting_approval", arguments: '{"recipient_email":"alex@example.com","amount":"50.00","currency":"USD"}' },
        { id: "approve-2", call_id: "send-1", tool_name: "paypal_send_invoice", status: "awaiting_approval", arguments: '{"invoice_id":"INV-DEMO-1042"}' },
      ] },
    ],
    approval: { run_id: "run-1", approval_id: "approval-1", calls: [
      { tool_name: "paypal_create_invoice", origin: "simulated", tool_call_id: "create-1", arguments: { recipient_email: "alex@example.com", amount: "50.00", currency: "USD" } },
      { tool_name: "paypal_send_invoice", origin: "simulated", tool_call_id: "send-1", arguments: { invoice_id: "INV-DEMO-1042" } },
    ] },
  });
  await openConversation(page, 1280, "Review these simulated invoice actions before they run.");
  await expect(page.getByRole("form", { name: "Tool approval" })).toBeVisible();
  await expect(page.getByText("No action in this review proceeds until you submit the decisions.")).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("approval-review.png"), fullPage: true });
});

test("restored clarification questions", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 1000 });
  await installFixture(page, {
    messages: [
      { id: 1, role: "user", content: "Show sales from last month." },
      { id: 2, role: "assistant", content: "I need one detail before I can total the results." },
    ],
    clarification: { run_id: "run-2", clarification_id: "clarify-1", questions: [
      { id: "currency", q: "Which currency should I report?", type: "radio", options: ["USD", "EUR", "Keep currencies separate"] },
      { id: "period", q: "Which month do you mean?", type: "radio", options: ["October 2026", "September 2026"] },
    ] },
  });
  await openConversation(page, 1280, "I need one detail before I can total the results.");
  await expect(page.getByRole("region", { name: "Clarification questions" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Which currency should I report?" })).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("clarification-questions.png"), fullPage: true });
});

test("tool catalog and connection setup", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 1200 });
  await installFixture(page, { messages: [] });
  await page.goto("/");
  await page.getByRole("button", { name: "Tool registry" }).click();
  await expect(page.getByRole("dialog").getByText("present_ui", { exact: true })).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("tool-catalog.png"), fullPage: true });
  await page.getByRole("button", { name: "MCP servers" }).click();
  await page.locator('details[aria-label="Research MCP"] > summary').click();
  await expect(page.getByRole("switch", { name: /search_runbooks/ })).toBeChecked();
  await expect(page.getByLabel("Effect of search_runbooks")).toHaveValue("read");
  await page.screenshot({ path: test.info().outputPath("connection-management.png"), fullPage: true });
  await page.locator("summary").filter({ hasText: "Add a connection" }).click();
  await expect(page.getByLabel("MCP endpoint URL")).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("connection-setup.png"), fullPage: true });
});

test("local model and embedding configuration", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 1300 });
  await installFixture(page, { messages: [] });
  await page.goto("/");
  await page.getByRole("button", { name: "Configure", exact: true }).click();
  await expect(page.getByRole("dialog").getByRole("heading", { name: "Configure LLM" })).toBeVisible();
  await expect(page.getByLabel("Embedding model name")).toHaveValue("jina-embeddings-v3");
  await expect(page.getByText("Saved keys are never displayed.")).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("model-configuration.png"), fullPage: true });
});
