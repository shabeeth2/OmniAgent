// Exercise the real component's handlers with deterministic hooks/timers, no DOM or provider.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const source = ts.transpileModule(readFileSync(new URL('../components/ClarificationCard.tsx', import.meta.url), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
}).outputText;

function mount(questions, submit) {
  const slots = [], effects = [], timers = new Map();
  let cursor = 0, timerId = 0, tree;
  const hook = initial => { const i = cursor++; if (!(i in slots)) slots[i] = typeof initial === 'function' ? initial() : initial; return i; };
  const React = {
    useState(initial) { const i = hook(initial); return [slots[i], value => { slots[i] = typeof value === 'function' ? value(slots[i]) : value; }]; },
    useRef(initial) { const i = hook({ current: initial }); return slots[i]; },
    useLayoutEffect() { cursor++; }, // Geometry is checked in the browser, not this handler harness.
    useEffect(callback, deps) {
      const i = cursor++;
      if (!slots[i] || deps.some((value, j) => value !== slots[i].deps[j])) {
        slots[i]?.cleanup?.();
        effects.push(() => { slots[i] = { deps, cleanup: callback() }; });
      }
    },
  };
  const jsx = (type, props) => ({ type, props });
  const context = { exports: {}, require(name) {
    if (name === 'react') return React;
    if (name === 'react/jsx-runtime') return { jsx, jsxs: jsx };
    if (name.endsWith('/button')) return { Button: 'Button' };
    if (name.endsWith('/GlideMenu')) return { default: 'GlideMenu' };
    return Object.fromEntries(['ArrowDown','ArrowUp','Check','CornerDownLeft','X'].map(name => [name, name]));
  }, setTimeout(callback) { const id = ++timerId; timers.set(id, callback); return id; }, clearTimeout(id) { timers.delete(id); },
  requestAnimationFrame: () => 0, cancelAnimationFrame() {}, ResizeObserver: class { observe() {} disconnect() {} } };
  vm.runInNewContext(source, context);
  const props = { questions, onSubmitted: submit };
  function render() { cursor = 0; tree = context.exports.default(props); effects.splice(0).forEach(effect => effect()); return tree; }
  function nodes(node) {
    if (!node || typeof node !== 'object') return [];
    return [node, ...[node.props?.children].flat(Infinity).flatMap(nodes)];
  }
  const find = predicate => { const found = nodes(tree).find(predicate); assert.ok(found, 'Expected control was rendered'); return found; };
  const text = node => node == null ? '' : typeof node === 'string' ? node : [node?.props?.children].flat(Infinity).map(text).join('');
  render();
  return {
    render, props, timers,
    choose(index) { nodes(tree).filter(n => n.type === 'input' && ['radio','checkbox'].includes(n.props.type))[index].props.onChange(); render(); },
    custom(value) { find(n => n.type === 'input' && n.props.placeholder).props.onChange({target:{value}}); render(); },
    click(name) { find(n => ['button','Button'].includes(n.type) && (n.props['aria-label'] === name || text(n) === name)).props.onClick(); render(); },
    async fire() { const pending = [...timers.values()]; timers.clear(); pending.forEach(callback => callback()); await new Promise(resolve => setImmediate(resolve)); render(); },
    async flush() { await new Promise(resolve => setImmediate(resolve)); render(); },
    alert() { return nodes(tree).find(n => n.props?.role === 'alert'); },
    unmount() { slots.forEach(slot => slot?.cleanup?.()); },
  };
}

const questions = [{id:'currency',q:'Which currency?',type:'radio',options:['USD','EUR']}];
let submitted;
const radio = mount(questions, async answers => { submitted = answers; });
radio.choose(1);
await radio.fire();
assert.equal(JSON.stringify(submitted), JSON.stringify([{question_id:'currency',selected:[1],custom:'',skipped:false}]));

submitted = undefined;
const custom = mount(questions, async answers => { submitted = answers; });
custom.choose(0);
custom.custom('GBP');
assert.equal(custom.timers.size, 0, 'Typing cancels radio auto-advance');
custom.click('Send');
await custom.flush();
assert.equal(submitted[0].custom, 'GBP');
assert.equal(submitted[0].selected.length, 0);

submitted = undefined;
const multi = mount([{...questions[0],type:'check'}], async answers => { submitted = answers; });
multi.choose(0); multi.choose(1);
assert.equal(multi.timers.size, 0);
assert.equal(submitted, undefined);
multi.custom('JPY'); multi.click('Send'); await multi.flush();
assert.equal(submitted[0].selected.length, 2);
assert.equal(submitted[0].custom, 'JPY');

const skipped = mount(questions, async answers => { submitted = answers; });
skipped.choose(0); skipped.click('Skip'); await skipped.flush();
assert.equal(submitted[0].skipped, true);
assert.equal(submitted[0].selected.length, 0);
assert.equal(skipped.timers.size, 0);

const multiple = [...questions, {id:'recipient',q:'Recipient?',type:'radio',options:[]}];
const back = mount(multiple, async answers => { submitted = answers; });
back.choose(1); await back.fire(); back.click('Previous question');
back.click('Continue'); back.custom('person@example.com'); back.click('Send'); await back.flush();
assert.equal(submitted[0].selected[0], 1, 'Previous answer survives navigation');
assert.equal(submitted[1].custom, 'person@example.com');
const bypass = mount(multiple, async answers => { submitted = answers; });
bypass.click('Next question'); bypass.custom('person@example.com'); bypass.click('Send'); await bypass.flush();
assert.equal(submitted[0].skipped, true, 'Bypassed questions are explicit skips');

let attempts = 0;
const failure = mount(questions, async answers => { attempts++; if (attempts === 1) throw new Error('Offline'); submitted = answers; });
failure.custom('GBP'); failure.click('Send'); await failure.flush();
assert.ok(failure.alert(), 'Failure is visible instead of a sent state');
failure.click('Send'); await failure.flush();
assert.equal(submitted[0].custom, 'GBP', 'Failure retains answers');

for (const action of ['dismiss','unmount','disabled']) {
  const card = mount(questions, async () => {});
  card.choose(0);
  if (action === 'dismiss') card.click('Dismiss questions');
  if (action === 'unmount') card.unmount();
  if (action === 'disabled') { card.props.disabled = true; card.render(); }
  assert.equal(card.timers.size, 0, `${action} cancels auto-advance`);
}
console.log('Clarification card answer, navigation, timer and failure checks passed');
