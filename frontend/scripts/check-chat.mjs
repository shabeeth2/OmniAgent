import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
const source = ts.transpileModule(readFileSync(new URL('../lib/chat.ts', import.meta.url), 'utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText;
async function run(chunks, onTrace) {
  const context = {exports:{}, process:{env:{}}, AbortSignal, TextDecoder, fetch:async()=>({ok:true,body:{getReader:()=>({read:async()=>chunks.length?{done:false,value:new TextEncoder().encode(chunks.shift())}:{done:true},cancel:async()=>{},releaseLock(){}})}})};
  vm.runInNewContext(source,context);
  return context.exports.sendChatMessage('hello', undefined, undefined, undefined, undefined, onTrace);
}
const result = await run(['data: {"conversation_id":7}\n\ndata: {"cont','ent":"Hello"}\n\ndata: [DONE]\n\n']);
assert.equal(result.message,'Hello');
assert.equal(result.conversation_id,7);
await assert.rejects(run(['data: {"content":"partial"}\n\n']), /before completion/);
await assert.rejects(run(['data: invalid\n\n']));
console.log('Streaming regression checks passed');
const approvalResult = await run(['data: {"conversation_id":7}\n\ndata: {"approval_required":{"run_id":"r","approval_id":"a","tool_name":"remote","origin":"api","arguments":{"id":1}}}\n\ndata: [DONE]\n\n']);
assert.equal(approvalResult.approval.approval_id, 'a');
assert.equal(approvalResult.message, '');
const traces = [];
await run(['data: {"conversation_id":7}\n\ndata: {"trace":{"id":"r:c","status":"running"}}\n\ndata: {"tra', 'ce":{"id":"r:c","status":"completed"}}\n\ndata: {"content":"done"}\n\ndata: [DONE]\n\n'], trace => traces.push(trace));
assert.equal(traces.length, 2);
assert.equal(traces[0].id, traces[1].id);
assert.equal(traces[1].status, 'completed');

// Restore and decide a simulated action using fake HTTP only; no provider is contacted.
const simulatedApproval = { run_id: 'demo-run', approval_id: 'send/invoice', tool_name: 'paypal_send_invoice', origin: 'simulated', tool_call_id: 'call-1', arguments: { invoice_id: 'SIM-1' } };
const requests = [];
const decisionChunks = [
  `data: ${JSON.stringify({ trace: { id: 'demo-run:call-1', call_id: 'call-1', tool_name: 'paypal_send_invoice', status: 'completed', catalog_version: 'paypal-v1' } })}\n\n`,
  'data: {"content":"Simulated invoice recorded; no email sent."}\n\ndata: [DONE]\n\n',
];
const restoredContext = { exports: {}, process: { env: {} }, AbortSignal, TextDecoder, fetch: async (url, options) => {
  requests.push({ url, options });
  if (!options) return { ok: true, json: async () => simulatedApproval };
  return { ok: true, body: { getReader: () => ({ read: async () => decisionChunks.length ? { done: false, value: new TextEncoder().encode(decisionChunks.shift()) } : { done: true }, cancel: async () => {}, releaseLock() {} }) } };
} };
vm.runInNewContext(source, restoredContext);
const restoredApproval = await restoredContext.exports.getPendingApproval(7);
assert.equal(restoredApproval.origin, 'simulated');
assert.equal(restoredApproval.arguments.invoice_id, 'SIM-1');
const resumedTraces = [];
const resumed = await restoredContext.exports.resumeApproval(7, restoredApproval.approval_id, 'approve', () => {}, () => {}, trace => resumedTraces.push(trace));
assert.equal(requests[0].url, 'http://localhost:8000/api/conversations/7/pending-approval');
assert.equal(requests[1].url, 'http://localhost:8000/api/conversations/7/approvals/send%2Finvoice');
assert.equal(JSON.parse(requests[1].options.body).decision, 'approve');
assert.equal(resumed.conversation_id, 7);
assert.equal(resumed.approval, undefined);
assert.match(resumed.message, /no email sent/);
assert.equal(resumedTraces[0].catalog_version, 'paypal-v1');
console.log('Simulated approval restore and resume checks passed');

// A restored risky-call batch retains IDs and sends independent decisions together.
const batchApproval = {run_id:'batch-run',approval_id:'batch/1',calls:[
  {tool_call_id:'write-a',tool_name:'append_note',origin:'api',arguments:{text:'note'}},
  {tool_call_id:'write-b',tool_name:'delete_note',origin:'mcp',arguments:{id:2}},
]};
restoredContext.fetch = async (url, options) => {
  requests.push({url,options});
  if (!options) return {ok:true,json:async()=>batchApproval};
  const chunks = ['data: {"content":"Approved append; deletion rejected."}\n\ndata: [DONE]\n\n'];
  return {ok:true,body:{getReader:()=>({read:async()=>chunks.length?{done:false,value:new TextEncoder().encode(chunks.shift())}:{done:true},cancel:async()=>{},releaseLock(){}})}};
};
const restoredBatch = await restoredContext.exports.getPendingApproval(7);
assert.equal(restoredBatch.calls.length, 2);
const decisions = [{tool_call_id:'write-a',decision:'approve'},{tool_call_id:'write-b',decision:'reject'}];
const batchResult = await restoredContext.exports.resumeApproval(7,restoredBatch.approval_id,decisions,()=>{},()=>{});
assert.deepEqual(JSON.parse(requests.at(-1).options.body), {decisions});
assert.match(requests.at(-1).url, /approvals\/batch%2F1$/);
assert.match(batchResult.message, /deletion rejected/);
const batchStream = await run([`data: {"conversation_id":7}\n\ndata: {"approval_required":${JSON.stringify(batchApproval)}}\n\ndata: [DONE]\n\n`]);
assert.deepEqual(JSON.parse(JSON.stringify(batchStream.approval)), batchApproval);
console.log('Batch approval SSE, restore, and decision serialization checks passed');

// Exercise the actual approval form handlers: no defaults and no partial batch.
const approvalCardSource = ts.transpileModule(readFileSync(new URL('../components/ApprovalCard.tsx', import.meta.url), 'utf8'), {
  compilerOptions: {module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX},
}).outputText;
let choices = {}, submission;
const jsx = (type, props) => ({type,props});
const cardContext = {exports:{},require(name) {
  if (name === 'react') return {useState:()=>[choices,value=>{choices=typeof value==='function'?value(choices):value;}]};
  if (name === 'react/jsx-runtime') return {jsx,jsxs:jsx};
  return {Button:'Button'};
}};
vm.runInNewContext(approvalCardSource,cardContext);
function nodes(node) { return !node || typeof node !== 'object' ? [] : [node,...[node.props?.children].flat(Infinity).flatMap(nodes)]; }
const cardProps = {approval:batchApproval,disabled:false,onSubmit:async value=>{submission=value;}};
let card = cardContext.exports.default(cardProps);
const controls = () => nodes(card);
assert.equal(controls().filter(node=>node.type==='input' && node.props.checked).length,0);
assert.equal(controls().find(node=>node.type==='Button').props.disabled,true);
card.props.onSubmit({preventDefault(){}});
assert.equal(submission,undefined);
controls().filter(node=>node.type==='input')[0].props.onChange();
card = cardContext.exports.default(cardProps);
assert.equal(controls().find(node=>node.type==='Button').props.disabled,true);
controls().filter(node=>node.type==='input')[3].props.onChange();
card = cardContext.exports.default(cardProps);
assert.equal(controls().find(node=>node.type==='Button').props.disabled,false);
card.props.onSubmit({preventDefault(){}});
assert.deepEqual(JSON.parse(JSON.stringify(submission)),decisions);
console.log('Batch approval explicit-choice and complete-submission checks passed');

const clarification = {run_id:'r',clarification_id:'q/1',questions:[{id:'currency',q:'Which currency?',type:'radio',options:['USD','EUR']}]};
const questionResult = await run([
  'data: {"conversation_id":7}\n\ndata: {"clarific',
  `ation_required":${JSON.stringify(clarification)}}\n\ndata: [DONE]\n\n`,
]);
assert.equal(questionResult.clarification.clarification_id, 'q/1');
restoredContext.fetch = async (url, options) => {
  requests.push({url,options});
  if (!options) return {ok:true,json:async()=>clarification};
  const chunks = ['data: {"content":"EUR selected"}\n\ndata: [DONE]\n\n'];
  return {ok:true,body:{getReader:()=>({read:async()=>chunks.length?{done:false,value:new TextEncoder().encode(chunks.shift())}:{done:true},cancel:async()=>{},releaseLock(){}})}};
};
assert.equal((await restoredContext.exports.getPendingClarification(7)).clarification_id, 'q/1');
const answers = [{question_id:'currency',selected:[1],custom:'',skipped:false}];
const clarified = await restoredContext.exports.resumeClarification(7,'q/1',answers,()=>{},()=>{});
assert.match(requests.at(-1).url, /clarifications\/q%2F1$/);
assert.deepEqual(JSON.parse(requests.at(-1).options.body), {answers});
assert.equal(clarified.message, 'EUR selected');
console.log('Clarification SSE, restore and resume checks passed');

const stateRequests = [];
restoredContext.fetch = async (url, options) => {
  stateRequests.push({url,options});
  if (url.endsWith('/api/conversations/7')) return {ok:true,json:async()=>({messages:[{id:9,role:'assistant',content:'Saved answer'}]})};
  if (url.endsWith('/pending-approval')) return {ok:true,json:async()=>batchApproval};
  return {ok:true,json:async()=>clarification};
};
const savedState = await restoredContext.exports.getSavedConversationState(7);
assert.deepEqual(JSON.parse(JSON.stringify(savedState.messages)), [{id:9,role:'assistant',content:'Saved answer'}]);
assert.equal(savedState.approval.approval_id, 'batch/1');
assert.equal(savedState.clarification.clarification_id, 'q/1');
assert.equal(stateRequests.length, 3);
assert.ok(stateRequests.every(({options}) => options === undefined), 'Uncertain request reconciliation performs saved-state reads only');
console.log('Saved conversation and pending-status reconciliation checks passed');
