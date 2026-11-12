import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const source = ts.transpileModule(readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
}).outputText;

function mount({ readSavedState, send = async () => ({}) }) {
  const slots = [], pendingEffects = [];
  let cursor = 0, tree;
  const React = {
    useState(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = typeof initial === "function" ? initial() : initial;
      return [slots[index], value => { slots[index] = typeof value === "function" ? value(slots[index]) : value; }];
    },
    useRef(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = { current: initial };
      return slots[index];
    },
    useCallback(callback, deps) {
      const index = cursor++;
      if (!slots[index] || deps.some((value, at) => value !== slots[index].deps[at])) slots[index] = { callback, deps };
      return slots[index].callback;
    },
    useEffect(callback, deps) {
      const index = cursor++;
      if (!slots[index] || deps.some((value, at) => value !== slots[index].deps[at])) {
        pendingEffects.push(() => {
          slots[index]?.cleanup?.();
          slots[index] = { deps, cleanup: callback() };
        });
      }
    },
  };
  const jsx = (type, props) => ({ type, props });
  const component = name => ({ __esModule: true, default: name });
  const context = {
    exports: {},
    process: { env: {} },
    crypto: { randomUUID: (() => { let id = 0; return () => `local-${++id}`; })() },
    fetch: async () => ({ ok: true, json: async () => conversations }),
    requestAnimationFrame: callback => { callback(); return 1; },
    cancelAnimationFrame() {},
    setTimeout,
    clearTimeout,
    require(name) {
      if (name === "react") return React;
      if (name === "react/jsx-runtime") return { jsx, jsxs: jsx };
      if (name === "lucide-react") return Object.fromEntries(["ArrowUpRight", "Code2", "Compass", "Copy", "Check", "Menu", "MessageSquare", "PenLine", "Plus", "X"].map(icon => [icon, icon]));
      if (name === "@/components/ui/button") return { Button: "Button" };
      if (name === "@/components/ui/dialog") return { Dialog: "Dialog", DialogContent: "DialogContent", DialogTitle: "DialogTitle", DialogDescription: "DialogDescription" };
      if (name === "@/components/ToolRegistry") return component("ToolRegistry");
      if (name === "@/components/ToolTraces") return component("ToolTraces");
      if (name === "@/components/SidebarNav") return component("SidebarNav");
      if (name === "@/components/PromptBar") return component("PromptBar");
      if (name === "@/components/ClarificationCard") return component("ClarificationCard");
      if (name === "@/components/ApprovalCard") return component("ApprovalCard");
      if (name === "@/components/ai-elements/conversation") return { Conversation: "Conversation", ConversationContent: "ConversationContent", ConversationScrollButton: "ConversationScrollButton" };
      if (name === "@/components/ai-elements/message") return { MessageResponse: "MessageResponse" };
      if (name === "@/lib/chat") return {
        sendChatMessage: send,
        getPendingApproval: async () => null,
        getPendingClarification: async () => null,
        getSavedConversationState: readSavedState,
        resumeApproval: async () => ({}),
        resumeClarification: async () => ({}),
      };
      throw new Error(`Unexpected import: ${name}`);
    },
  };
  vm.runInNewContext(source, context);
  function render() {
    cursor = 0;
    tree = context.exports.default();
    pendingEffects.splice(0).forEach(effect => effect());
    return tree;
  }
  function nodes(node) {
    if (!node || typeof node !== "object") return [];
    return [node, ...[node.props?.children].flat(Infinity).flatMap(nodes)];
  }
  const find = (type, predicate = () => true) => {
    const found = nodes(tree).find(node => node.type === type && predicate(node.props));
    assert.ok(found, `Expected ${type} control`);
    return found;
  };
  const text = node => node == null ? "" : typeof node === "string" ? node : [node?.props?.children].flat(Infinity).map(text).join("");
  return { render, find, nodes, text, slots };
}

const conversations = [
  { id: 1, title: "First", messages: [{ id: 11, role: "user", content: "First question" }] },
  { id: 2, title: "Second", messages: [{ id: 22, role: "user", content: "Second question" }] },
];
let attempts = 0;
const retry = mount({
  readSavedState: async id => {
    attempts++;
    if (attempts === 1) throw new Error("Offline");
    return { messages: [{ id: id * 100, role: "user", content: "restored" }], approval: null, clarification: null };
  },
});
retry.render();
await new Promise(setImmediate);
retry.render();
retry.find("SidebarNav").props.onPick("1", "First");
retry.render();
await new Promise(setImmediate);
retry.render();
assert.equal(retry.find("PromptBar").props.disabled, true, "failed restore keeps submission disabled");
const retryButton = retry.find("Button", props => retry.text(props.children) === "Retry status");
retryButton.props.onClick();
retry.render();
await new Promise(setImmediate);
retry.render();
assert.equal(attempts, 2, "retry explicitly reloads saved state");
assert.equal(retry.find("PromptBar").props.disabled, false, "successful retry unlocks the composer");
console.log("Pending status failure and explicit retry checks passed");

let releaseFirst;
const stale = mount({
  readSavedState: id => id === 1
    ? new Promise(resolve => { releaseFirst = resolve; })
    : Promise.resolve({ messages: [{ id: 200, role: "user", content: "Second saved" }], approval: null, clarification: null }),
});
stale.render();
await new Promise(setImmediate);
stale.render();
stale.find("SidebarNav").props.onPick("1", "First");
stale.render();
stale.find("SidebarNav").props.onPick("2", "Second");
stale.render();
await new Promise(setImmediate);
releaseFirst({ messages: [{ id: 100, role: "user", content: "Stale first" }], approval: { approval_id: "stale" }, clarification: null });
await new Promise(setImmediate);
const staleTree = stale.render();
assert.equal(stale.find("PromptBar").props.disabled, false, "stale restore cannot lock the newly selected conversation");
assert.ok(!stale.nodes(staleTree).some(node => node.type === "ApprovalCard"), "stale approval is not applied to the newly selected session");
assert.ok(!stale.text(staleTree).includes("Stale first"), "stale conversation messages are ignored");
console.log("Stale conversation restore guard checks passed");

let savedMessages = [{ id: 11, role: "user", content: "First question" }];
const canonical = mount({
  readSavedState: async () => ({ messages: savedMessages, approval: null, clarification: null }),
  send: async (message, conversationId, onChunk, onConversation) => {
    onConversation(conversationId);
    onChunk("Streamed answer");
    savedMessages = [...savedMessages, { id: 12, role: "user", content: message }, { id: 13, role: "assistant", content: "Streamed answer" }];
    return { approval: null, clarification: null };
  },
});
canonical.render();
await new Promise(setImmediate);
canonical.render();
canonical.find("SidebarNav").props.onPick("1", "First");
canonical.render();
await new Promise(setImmediate);
canonical.render();
await canonical.find("PromptBar").props.onSend("Follow-up");
canonical.render();
await new Promise(setImmediate);
canonical.render();
canonical.find("SidebarNav").props.onPick("2", "Second");
canonical.render();
await new Promise(setImmediate);
canonical.render();
canonical.find("SidebarNav").props.onPick("1", "First");
canonical.render();
await new Promise(setImmediate);
const canonicalTree = canonical.render();
assert.ok(canonical.text(canonicalTree).includes("Follow-up"), "active session keeps the new user message after switching away and back");
assert.ok(canonical.text(canonicalTree).includes("Streamed answer"), "active session keeps streamed assistant content after switching away and back");
console.log("Canonical conversation message state checks passed");
