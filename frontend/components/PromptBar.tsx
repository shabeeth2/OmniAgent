"use client";

import { useCallback, useLayoutEffect, useRef, useState } from "react";

export default function PromptBar({
  placeholder,
  onSend,
  initialDraft = "",
  disabled = false,
}: {
  placeholder?: string;
  onSend?: (text: string) => void;
  initialDraft?: string;
  disabled?: boolean;
}) {
  const [draft, setDraft] = useState(initialDraft);
  const controls = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);

  const resize = useCallback(() => {
    const textarea = input.current;
    if (!textarea) return;
    textarea.style.height = "0px";
    const height = textarea.scrollHeight;
    textarea.style.height = `${Math.min(Math.max(height, 32), 160)}px`;
    textarea.style.overflowY = height > 160 ? "auto" : "hidden";
  }, []);

  useLayoutEffect(() => {
    const container = controls.current;
    if (!container) return;
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(container);
    return () => observer.disconnect();
  }, [resize]);

  useLayoutEffect(resize, [draft, resize]);

  function send() {
    const message = draft.trim();
    if (!message || disabled) return;
    onSend?.(message);
    setDraft("");
  }

  return (
    <div data-promptbar className="live-prompt w-full">
      <div className="relative">
        <div ref={controls} className="relative grid grid-cols-[minmax(0,1fr)_32px] items-end gap-2 overflow-hidden rounded-2xl border border-line bg-surface p-2 shadow-card transition-colors focus-within:border-ring">
          <textarea
            ref={input}
            rows={1}
            disabled={disabled}
            value={draft}
            onChange={event => setDraft(event.target.value)}
            onKeyDown={event => {
              if (event.nativeEvent.isComposing) return;
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                send();
              }
            }}
            placeholder={placeholder ?? "Write a message…"}
            aria-label="Prompt"
            className="min-h-8 w-full min-w-0 resize-none bg-transparent px-3 py-1.5 text-sm leading-5 text-ink outline-none [overflow-wrap:anywhere] placeholder:text-ink-3"
          />
          <button
            type="button"
            aria-label="Send"
            disabled={disabled || !draft.trim()}
            onClick={send}
            className="flex size-8 shrink-0 items-center justify-center rounded-full transition-colors disabled:cursor-not-allowed"
            style={{
              background: draft.trim() && !disabled ? "var(--ink)" : "var(--line-strong)",
              color: draft.trim() && !disabled ? "var(--surface)" : "var(--ink-2)",
            }}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M12 19V5M5 12l7-7 7 7" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}
