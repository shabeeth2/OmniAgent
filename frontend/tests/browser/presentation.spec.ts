import { test, expect } from "@playwright/test";
import { execFile } from "node:child_process";
import { promisify } from "node:util";

test("compiled styles", async () => {
  const result = await promisify(execFile)(process.execPath, ["scripts/check-styles.mjs", "http://127.0.0.1:3100"]);
  expect(result.stdout).toContain("Styles verified");
});

const surface = (kind: "BarChart" | "LineChart", title: string) => ({
  id: "shared-id", title, source: "User supplied fixture", incomplete: false,
  messages: [
    { version: "v0.9", createSurface: { surfaceId: "shared-id", catalogId: "urn:agent-tool-scale:read-only:v1" } },
    { version: "v0.9", updateComponents: { surfaceId: "shared-id", components: [
      { id: "root", component: "Column", children: ["metric", "chart", "table"] },
      { id: "metric", component: "Metric", label: "Total USD", value: "125" },
      { id: "chart", component: kind, title: "Monthly sales", unit: "USD", points: [{ label: "Sep", value: 50 }, { label: "Oct", value: 75 }] },
      { id: "table", component: "Table", columns: ["Month", "USD"], rows: [["Sep", 50], ["Oct", 75]] },
    ] } },
  ],
});

for (const width of [1280, 390]) {
  test(`charts, restoration and malformed fallback at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    const conversation: { id: number; title: string; messages: { id: number; role: string; content: string; ui_surfaces?: unknown[] }[] } = { id: 1, title: "Visual fixture", messages: [
      { id: 1, role: "user", content: "Show sample sales" },
      { id: 2, role: "assistant", content: "**Fixture summary:** USD 125.", ui_surfaces: [surface("BarChart", "Sales bars")] },
      { id: 3, role: "assistant", content: "Trend summary.", ui_surfaces: [surface("LineChart", "Sales trend")] },
    ] };
    await page.route("**/api/**", async route => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/api/conversations") return route.fulfill({ json: [conversation] });
      if (path === "/api/conversations/1") return route.fulfill({ json: conversation });
      if (path.includes("pending-")) return route.fulfill({ json: null });
      if (path === "/api/chat") {
        const message = { id: 4, role: "assistant", content: "Text remains available.", ui_surfaces: [{ bad: true }] };
        conversation.messages.push(message);
        return route.fulfill({ contentType: "text/event-stream", body: `data: ${JSON.stringify({ conversation_id: 1 })}\n\ndata: ${JSON.stringify({ ui_surfaces: message.ui_surfaces })}\n\ndata: ${JSON.stringify({ content: message.content })}\n\ndata: [DONE]\n\n` });
      }
      return route.fulfill({ status: 404, json: {} });
    });
    async function selectSaved() {
      if (width < 768) await page.getByRole("button", { name: "Open navigation" }).click();
      await page.getByRole("button", { name: "Visual fixture", exact: true }).click();
      await expect(page.getByRole("region", { name: "Sales bars", exact: true })).toBeVisible();
    }
    await page.goto("/");
    await selectSaved();
    await expect(page.locator(".recharts-surface")).toHaveCount(2);
    await expect(page.getByRole("definition")).toHaveCount(2);
    await expect(page.getByText("Fixture summary:")).toBeVisible();
    await page.getByText("View chart data", { exact: true }).first().click();
    await expect(page.getByRole("columnheader", { name: "Label", exact: true })).toBeVisible();
    await expect(page.locator("body")).toHaveJSProperty("scrollWidth", width);
    await page.screenshot({ path: testInfo.outputPath("charts.png"), fullPage: true });
    await page.reload();
    await selectSaved();
    await expect(page.locator(".recharts-surface")).toHaveCount(2);
    await page.getByRole("textbox", { name: "Prompt" }).fill("Show malformed fixture");
    await page.getByRole("button", { name: "Send", exact: true }).click();
    await expect(page.getByText("Text remains available.", { exact: true })).toBeVisible();
    await expect(page.getByText("This visual could not be displayed. Refer to the response text.")).toBeVisible();
    await expect(page.locator(".recharts-surface")).toHaveCount(2);
    expect(errors).toEqual([]);
  });
}
