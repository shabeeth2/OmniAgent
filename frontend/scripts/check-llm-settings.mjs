import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const code = ts.transpileModule(readFileSync(new URL("../lib/llm-settings.ts", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
let request;
let response = { ok: true, json: async () => ({ llm_model: "saved-model" }) };
const context = { exports: {}, process: { env: {} }, AbortSignal, fetch: async (url, options) => { request = { url, ...options }; return response; } };
vm.runInNewContext(code, context);
const { loadLlmSettings, saveLlmSettings } = context.exports;
assert.equal((await loadLlmSettings()).llm_model, "saved-model");
assert.equal(request.url, "http://localhost:8000/api/settings/llm");
assert.equal(request.cache, "no-store");
await saveLlmSettings({ llm_model: "chat", llm_api_key_configured: true, embedding_api_key_configured: true }, "", "");
assert.equal(request.method, "PUT");
assert.equal(JSON.stringify(JSON.parse(request.body)), '{"llm_model":"chat"}');
await saveLlmSettings({ llm_model: "chat" }, "new-key", "embedding-key");
assert.equal(JSON.parse(request.body).llm_api_key, "new-key");
assert.equal(JSON.parse(request.body).embedding_api_key, "embedding-key");
response = { ok: false, status: 422, json: async () => ({ detail: "provider echoed secret" }) };
await assert.rejects(() => saveLlmSettings({ llm_model: "chat" }, "", ""), /Check the model settings/);
response = { ok: false, status: 500 };
await assert.rejects(() => loadLlmSettings(), /Check the backend connection/);
console.log("LLM settings request, secret preservation, and error checks passed");
