"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { ArrowDown, ArrowUp, Check, CornerDownLeft, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import GlideMenu from "@/components/primitives/GlideMenu";
import type { ClarificationAnswer, ClarificationQuestion } from "@/lib/chat";

const SLIDE = "360ms cubic-bezier(0.22, 1, 0.36, 1)";

function RollingDigits({ value }: { value: string }) {
  const previous = useRef(value);
  const [from, setFrom] = useState(value);
  const [shifted, setShifted] = useState(false);
  useEffect(() => {
    const old = previous.current;
    previous.current = value;
    setFrom(old);
    setShifted(false);
    let second = 0;
    const first = requestAnimationFrame(() => { second = requestAnimationFrame(() => setShifted(true)); });
    const timer = setTimeout(() => setFrom(value), 400);
    return () => { cancelAnimationFrame(first); cancelAnimationFrame(second); clearTimeout(timer); };
  }, [value]);
  const down = parseInt(value) < parseInt(from);
  return <span aria-hidden="true" className="inline-flex h-4 overflow-hidden font-mono text-xs tabular-nums">
    {[...value].map((character, index) => from[index] === character ? <span key={index}>{character === " " ? "\u00a0" : character}</span> : (
      <span key={`${index}-${value}`} className="inline-block h-4 overflow-hidden">
        <span className="flex flex-col transition-transform duration-300 motion-reduce:transition-none" style={{ transform: `translateY(${down ? shifted ? "0" : "-16px" : shifted ? "-16px" : "0"})` }}>
          <span className="h-4">{down ? character : from[index]}</span><span className="h-4">{down ? from[index] : character}</span>
        </span>
      </span>
    ))}
  </span>;
}

export default function ClarificationCard({ questions, onSubmitted, disabled = false }: {
  questions: ClarificationQuestion[];
  onSubmitted: (answers: ClarificationAnswer[]) => Promise<void>;
  disabled?: boolean;
}) {
  const [qi, setQi] = useState(0);
  const [answers, setAnswers] = useState<Record<string, ClarificationAnswer>>(() => Object.create(null));
  const answersRef = useRef(answers);
  const [sent, setSent] = useState(false);
  const [sending, setSending] = useState(false);
  const submitting = useRef(false);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(true);
  const advanceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const questionRefs = useRef<(HTMLDivElement | null)[]>([]);
  const [viewport, setViewport] = useState({ height: undefined as number | undefined, y: 0 });
  const [ready, setReady] = useState(false);
  const question = questions[qi];
  const current = answers[question.id];
  const hasAnswer = !!(current?.selected.length || current?.custom.trim());
  const last = qi === questions.length - 1;
  const locked = sending || disabled;

  const cancelAdvance = () => {
    if (advanceTimer.current) clearTimeout(advanceTimer.current);
    advanceTimer.current = null;
  };
  useEffect(() => () => { if (advanceTimer.current) clearTimeout(advanceTimer.current); }, []);
  useEffect(() => { if (disabled || !open) cancelAdvance(); }, [disabled, open]);

  useLayoutEffect(() => {
    if (!open || sent) return;
    const item = questionRefs.current[qi];
    if (!item) return;
    const measure = () => setViewport(previous => {
      const next = { height: item.offsetHeight, y: item.offsetTop };
      return previous.height === next.height && previous.y === next.y ? previous : next;
    });
    measure();
    setReady(true);
    const observer = new ResizeObserver(measure);
    observer.observe(item);
    return () => observer.disconnect();
  }, [qi, open, sent, ready]);
  useEffect(() => {
    if (!open || sent) return;
    const frame = requestAnimationFrame(() => questionRefs.current[qi]?.querySelector<HTMLElement>("h3")?.focus({ preventScroll: true }));
    return () => cancelAnimationFrame(frame);
  }, [qi, open, sent]);

  function update(answer: ClarificationAnswer) {
    answersRef.current = Object.assign(Object.create(null), answersRef.current, { [answer.question_id]: answer });
    setAnswers(answersRef.current);
    setError("");
  }
  function goTo(index: number) {
    cancelAdvance();
    setQi(Math.max(0, Math.min(questions.length - 1, index)));
  }
  async function send() {
    cancelAdvance();
    if (submitting.current || disabled) return;
    submitting.current = true;
    setSending(true);
    setError("");
    const batch = questions.map(q => {
      const answer = answersRef.current[q.id];
      return answer && (answer.selected.length || answer.custom.trim()) ? { ...answer, custom: answer.custom.trim(), skipped: false }
        : { question_id: q.id, selected: [], custom: "", skipped: true };
    });
    try { await onSubmitted(batch); setSent(true); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "Could not send answers. Try again"); }
    finally { submitting.current = false; setSending(false); }
  }
  function advance() { if (last) void send(); else goTo(qi + 1); }
  function select(index: number) {
    cancelAdvance();
    const picked = answersRef.current[question.id]?.selected ?? [];
    update({ question_id: question.id,
      selected: question.type === "radio" ? [index] : picked.includes(index) ? picked.filter(i => i !== index) : [...picked, index],
      custom: question.type === "radio" ? "" : answersRef.current[question.id]?.custom ?? "", skipped: false });
    if (question.type === "radio") advanceTimer.current = setTimeout(advance, 480);
  }
  function skip() {
    cancelAdvance();
    update({ question_id: question.id, selected: [], custom: "", skipped: true });
    advance();
  }

  if (!open) return <Button type="button" variant="outline" size="sm" onClick={() => setOpen(true)}>Answer questions</Button>;
  if (sent) return <p role="status" className="flex items-center gap-2 text-sm text-ink-2"><Check size={16} />Answers sent</p>;

  return <section aria-label="Clarification questions" aria-busy={sending} className="clarification-card w-full max-w-80 rounded-card border border-line bg-surface">
    <div className="relative p-4">
      <Button type="button" variant="ghost" size="icon-sm" aria-label="Dismiss questions" disabled={locked} onClick={() => { cancelAdvance(); setOpen(false); }} className="absolute right-2 top-2 z-10 text-ink-3"><X size={16} /></Button>
      <div className="clarification-viewport overflow-hidden" style={{ height: viewport.height, transition: ready ? `height ${SLIDE}` : undefined }}>
        <div className="relative flex flex-col gap-6" style={{ transform: `translate3d(0, ${-viewport.y}px, 0)`, transition: ready ? `transform ${SLIDE}` : undefined }}>
          {questions.map((q, index) => {
            const active = index === qi;
            if (!ready && !active) return null;
            const answer = answers[q.id];
            return <div key={q.id} ref={element => { questionRefs.current[index] = element; }} inert={!active} aria-hidden={!active} style={{ opacity: active ? 1 : 0, pointerEvents: active ? undefined : "none", transition: `opacity ${SLIDE}` }}>
              <h3 id={`question-${q.id}`} tabIndex={-1} className="pr-8 text-sm font-medium leading-5 text-ink outline-none">{q.q}</h3>
              <fieldset disabled={locked} aria-labelledby={`question-${q.id}`} className="mt-3 min-w-0">
                <GlideMenu className="flex flex-col gap-1" highlightClassName="inset-x-0 rounded-control bg-hover">
                  {q.options.map((option, optionIndex) => {
                    const selected = answer?.selected.includes(optionIndex) ?? false;
                    return <label key={option} data-menu-row className="relative z-10 flex min-h-8 cursor-pointer items-center gap-2 rounded-control px-1 py-1 text-sm text-ink-2 focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-ring">
                      <input type={q.type === "radio" ? "radio" : "checkbox"} name={`clarification-${q.id}`} checked={selected} onChange={() => select(optionIndex)} className="peer sr-only" />
                      <span aria-hidden="true" className={`flex size-4 shrink-0 items-center justify-center border ${q.type === "radio" ? "rounded-full" : "rounded-[4px]"} ${selected ? "border-ink bg-ink text-surface" : "border-line-strong"}`}>
                        {selected && (q.type === "radio" ? <span className="size-1.5 rounded-full bg-surface" /> : <Check size={12} strokeWidth={3} />)}
                      </span>
                      <span className={`min-w-0 break-words leading-5 ${selected ? "text-ink" : ""}`}>{option}</span>
                    </label>;
                  })}
                  <label data-menu-row className="relative z-10 block rounded-control px-1 py-2 focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-ring">
                    <span className="sr-only">Custom answer for {q.q}</span>
                    <input value={answer?.custom ?? ""} maxLength={2000} placeholder="Something else…" className="w-full min-w-0 bg-transparent px-1 text-sm leading-5 text-ink outline-none placeholder:text-ink-3"
                      onChange={event => { cancelAdvance(); update({ question_id: q.id, selected: q.type === "radio" ? [] : answer?.selected ?? [], custom: event.target.value, skipped: false }); }}
                      onKeyDown={event => { if (event.key === "Enter" && hasAnswer && !event.nativeEvent.isComposing) { event.preventDefault(); advance(); } }} />
                  </label>
                </GlideMenu>
              </fieldset>
            </div>;
          })}
        </div>
      </div>
    </div>
    {error && <p role="alert" className="px-4 pb-3 text-xs text-destructive">{error}</p>}
    <footer className="flex items-center justify-between gap-2 border-t border-line px-4 py-3">
      <div className="flex items-center gap-1 text-ink-3">
        <button type="button" aria-label="Previous question" disabled={locked || qi === 0} onClick={() => goTo(qi - 1)} className="flex size-6 items-center justify-center disabled:opacity-30"><ArrowUp size={14} /></button>
        <span className="sr-only" role="status">Question {qi + 1} of {questions.length}</span>
        <RollingDigits value={`${qi + 1} / ${questions.length}`} />
        <button type="button" aria-label="Next question" disabled={locked || last} onClick={() => goTo(qi + 1)} className="flex size-6 items-center justify-center disabled:opacity-30"><ArrowDown size={14} /></button>
      </div>
      <div className="flex items-center gap-1">
        <Button type="button" variant="ghost" size="sm" disabled={locked} onClick={skip}>Skip</Button>
        <Button type="button" size="sm" disabled={locked || !hasAnswer} onClick={advance}>{sending ? "Sending…" : last ? "Send" : "Continue"}<CornerDownLeft size={14} /></Button>
      </div>
    </footer>
  </section>;
}
