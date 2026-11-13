import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import vm from "node:vm";
import ts from "typescript";

const require = createRequire(import.meta.url);
function load(file, extra = {}) {
  const source = ts.transpileModule(readFileSync(new URL(file, import.meta.url), "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
  const context = { exports: {}, require, TextEncoder, TextDecoder, AbortSignal, process: { env: {} }, ...extra };
  vm.runInNewContext(source, context);
  return context.exports;
}
const { parseSurface, CATALOG_ID } = load("../lib/presentation.ts");
const surface = {
  id: "same-id", title: "Sales", source: "User supplied fixture", incomplete: false,
  messages: [
    { version: "v0.9", createSurface: { surfaceId: "same-id", catalogId: CATALOG_ID } },
    { version: "v0.9", updateComponents: { surfaceId: "same-id", components: [{ id: "root", component: "Metric", label: "Total USD", value: "125" }] } },
  ],
};
assert.ok(parseSurface(surface));
for (const node of [
  { id: "root", component: "Button", action: "send" },
  { id: "root", component: "Text", text: "javascript:alert(1)" },
  { id: "root", component: "Column", children: ["root"] },
  { id: "root", component: "Column", children: ["missing"] },
  { id: "root", component: "Table", columns: ["a"], rows: [[1, 2]] },
  { id: "root", component: "Table", columns: ["a"], rows: Array(201).fill([1]) },
]) {
  const invalid = structuredClone(surface);
  invalid.messages[1].updateComponents.components = [node];
  assert.equal(parseSurface(invalid), null);
}
assert.equal(parseSurface({ ...surface, messages: [{ version: "v1.0" }] }), null);
const incoming = [[], [surface], [surface]];
let current = [];
const chunks = ['data: {"conversation_id":1}\n\n', ...incoming.map(ui_surfaces => `data: ${JSON.stringify({ ui_surfaces })}\n\n`), 'data: {"content":"Summary"}\n\ndata: [DONE]\n\n'].join("").match(/.{1,7}|\n/gs);
const api = load("../lib/chat.ts", { fetch: async () => ({ ok: true, body: { getReader: () => ({ read: async () => chunks.length ? { done: false, value: new TextEncoder().encode(chunks.shift()) } : { done: true }, cancel: async () => {}, releaseLock() {} }) } }) });
const result = await api.sendChatMessage("chart", undefined, undefined, undefined, undefined, undefined, undefined, surfaces => { current = surfaces; });
assert.equal(current.length, 1);
assert.equal(result.ui_surfaces.length, 1);
assert.equal(result.message, "Summary");
console.log("Presentation validation and fragmented SSE replacement checks passed");
