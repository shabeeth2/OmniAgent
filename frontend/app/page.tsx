"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowUpRight, Code2, Compass, Copy, Check, Menu, MessageSquare, PenLine, Plus, X } from "lucide-react";
import ToolRegistry from "@/components/ToolRegistry";
import ToolTraces from "@/components/ToolTraces";
import SidebarNav from "@/components/SidebarNav";
import PromptBar from "@/components/PromptBar";
import ClarificationCard from "@/components/ClarificationCard";
import ApprovalCard from "@/components/ApprovalCard";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Conversation, ConversationContent, ConversationScrollButton } from "@/components/ai-elements/conversation";
import { MessageResponse } from "@/components/ai-elements/message";
import { sendChatMessage, getSavedConversationState, resumeApproval, resumeClarification, type Approval, type ApprovalSubmission, type ToolTrace, type Clarification, type ClarificationAnswer } from "@/lib/chat";

type Message = { id: string; role: "user" | "assistant"; content: string; traces?: ToolTrace[] };
type Session = { id: string; title: string; messages: Message[]; conversationId?: number };
const starters = [
  { icon: Compass, title: "Create a PayPal invoice", prompt: "Draft a PayPal invoice for alex@example.com for USD 125. Ask me before sending it." },
  { icon: PenLine, title: "Review PayPal sales", prompt: "Show completed PayPal sales for October 2026. Retrieve every page and report a separate total for each currency." },
  { icon: Code2, title: "Find the runbook & status", prompt: "Find the deployment runbook in the knowledge base, then report the current system status." },
];

export default function ChatPage() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [approval, setApproval] = useState<Approval | null>(null);
  const [clarification, setClarification] = useState<Clarification | null>(null);
  const [restoring, setRestoring] = useState(true);
  const [pendingStatusError, setPendingStatusError] = useState(false);
  const [statusRetry, setStatusRetry] = useState(0);
  const [error, setError] = useState("");
  const [registryOpen, setRegistryOpen] = useState(false);
  const [navigationOpen, setNavigationOpen] = useState(false);
  const [seed, setSeed] = useState({ text: "", version: 0 });
  const [copied, setCopied] = useState<string | null>(null);
  const sending = useRef(false);
  const composer = useRef<HTMLDivElement>(null);
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => { if (copyTimer.current) clearTimeout(copyTimer.current); }, []);

  useEffect(() => {
    let cancelled = false;
    async function restore() {
      try {
        const base = process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000";
        const response = await fetch(`${base}/api/conversations`);
        if (!response.ok) throw new Error();
        const rows = await response.json();
        if (cancelled) return;
        setSessions(rows.map((row: { id: number; title: string; messages: (Omit<Message, "id"> & { id: number })[] }) => ({ id: String(row.id), conversationId: row.id, title: row.title, messages: row.messages.map(message => ({ ...message, id: String(message.id) })) })));
      } catch { if (!cancelled) setError("Could not restore conversations. Reload to retry."); }
      finally { if (!cancelled) setRestoring(false); }
    }
    void restore();
    return () => { cancelled = true; };
  }, []);

  const selectedSession = sessions.find(item => item.id === active);
  const messages = selectedSession?.messages ?? [];
  const selectedConversationId = selectedSession?.conversationId;
  const readSavedState = useCallback(async (conversationId: number) => {
    const state = await getSavedConversationState(conversationId);
    return { ...state, messages: state.messages.map(message => ({ ...message, id: String(message.id) })) };
  }, []);
  const applySavedState = useCallback((sessionId: string, state: Awaited<ReturnType<typeof readSavedState>>) => {
    setSessions(previous => previous.map(item => item.id === sessionId ? { ...item, messages: state.messages } : item));
    setApproval(state.approval);
    setClarification(state.clarification);
    setPendingStatusError(false);
    setRestoring(false);
  }, []);
  const reconcileSavedState = useCallback(async (sessionId: string, conversationId: number) => {
    try {
      applySavedState(sessionId, await readSavedState(conversationId));
      return true;
    } catch {
      setRestoring(true);
      setPendingStatusError(true);
      return false;
    }
  }, [applySavedState, readSavedState]);

  useEffect(() => {
    let cancelled = false;
    if (!selectedConversationId || busy) return;
    readSavedState(selectedConversationId)
      .then(state => { if (!cancelled && active) applySavedState(active, state); })
      .catch(() => { if (!cancelled) { setRestoring(true); setPendingStatusError(true); setError("Could not restore pending request status."); } });
    return () => { cancelled = true; };
  }, [active, selectedConversationId, busy, statusRetry, readSavedState, applySavedState]);

  function updateAssistant(sessionId: string, messageId: string, change: (message: Message) => Message) {
    const update = (items: Message[]) => items.map(message => message.id === messageId ? change(message) : message);
    setSessions(previous => previous.map(session => session.id === sessionId ? { ...session, messages: update(session.messages) } : session));
  }

  function receiveTrace(sessionId: string, messageId: string, trace: ToolTrace) {
    updateAssistant(sessionId, messageId, message => {
      const traces = message.traces ?? [];
      return { ...message, traces: traces.some(item => item.id === trace.id) ? traces.map(item => item.id === trace.id ? trace : item) : [...traces, trace] };
    });
  }

  async function decide(decision: ApprovalSubmission) {
    const session = sessions.find(item => item.id === active);
    if (!approval || !session?.conversationId || sending.current) return;
    sending.current = true;
    setBusy(true);
    setError("");
    const assistantId = session.messages.at(-1)?.id;
    if (!assistantId) { sending.current = false; setBusy(false); return; }
    let content = "";
    try {
      const result = await resumeApproval(session.conversationId, approval.approval_id, decision, chunk => {
        content += chunk;
        updateAssistant(session.id, assistantId, message => ({ ...message, content }));
      }, setApproval, trace => receiveTrace(session.id, assistantId, trace), setClarification);
      setApproval(result.approval ?? null);
      setClarification(result.clarification ?? null);
    } catch {
      await reconcileSavedState(session.id, session.conversationId);
      setError("Could not confirm the decision. Saved status was refreshed where available; check before trying again.");
    }
    finally { sending.current = false; setBusy(false); }
  }

  async function answerQuestions(answers: ClarificationAnswer[]) {
    const session = sessions.find(item => item.id === active);
    if (!clarification || !session?.conversationId || sending.current) throw new Error("Questions are no longer available");
    const pending = clarification;
    sending.current = true;
    setBusy(true);
    setError("");
    const assistantId = crypto.randomUUID();
    const summary = pending.questions.map(q => {
      const answer = answers.find(item => item.question_id === q.id)!;
      return `${q.q}\n${answer.skipped ? "Skipped (unanswered)" : [...answer.selected.map(i => q.options[i]), ...(answer.custom ? [answer.custom] : [])].join("; ")}`;
    }).join("\n\n");
    const next: Message[] = [...session.messages, { id: crypto.randomUUID(), role: "user", content: summary }, { id: assistantId, role: "assistant", content: "" }];
    setSessions(previous => previous.map(item => item.id === session.id ? { ...item, messages: next } : item));
    let content = "";
    try {
      const result = await resumeClarification(session.conversationId, pending.clarification_id, answers, chunk => {
        content += chunk;
        updateAssistant(session.id, assistantId, message => ({ ...message, content }));
      }, setClarification, setApproval, trace => receiveTrace(session.id, assistantId, trace));
      setClarification(result.clarification ?? null);
      setApproval(result.approval ?? null);
    } catch {
      // Reconcile uncertain submissions from saved state; never replay them automatically.
      await reconcileSavedState(session.id, session.conversationId);
      setError("Could not finish sending answers. Saved request status was refreshed where available; reopen the conversation before retrying if status is uncertain.");
      throw new Error("Could not confirm submission. Your answers are retained; check request status before retrying");
    } finally { sending.current = false; setBusy(false); }
  }

  function focusComposer() {
    requestAnimationFrame(() => composer.current?.querySelector("textarea")?.focus());
  }

  function prepareDraft(text: string) {
    setSeed(current => ({ text, version: current.version + 1 }));
    focusComposer();
  }

  function newChat() {
    if (sending.current) return;
    setApproval(null);
    setClarification(null);
    setRestoring(false);
    setPendingStatusError(false);
    setActive(null);
    setError("");
    setNavigationOpen(false);
    prepareDraft("");
  }

  function selectSession(id: string) {
    if (sending.current) return;
    const session = sessions.find(item => item.id === id);
    if (!session) return;
    if (active === id) {
      setNavigationOpen(false);
      if (pendingStatusError) { setError(""); setPendingStatusError(false); setStatusRetry(value => value + 1); }
      return;
    }
    setApproval(null);
    setClarification(null);
    setRestoring(true);
    setPendingStatusError(false);
    setActive(id);
    setError("");
    setNavigationOpen(false);
    prepareDraft("");
  }

  async function copyMessage(message: Message) {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(message.id);
      if (copyTimer.current) clearTimeout(copyTimer.current);
      copyTimer.current = setTimeout(() => setCopied(null), 2000);
    } catch {
      setError("Copy isn’t available in this browser. Select the response text to copy it.");
    }
  }

  async function send(text: string) {
    if (!text.trim() || sending.current || approval || clarification || restoring) return;
    sending.current = true;
    setBusy(true);
    setError("");
    const id = active ?? crypto.randomUUID();
    const assistantId = crypto.randomUUID();
    const next: Message[] = [
      ...messages,
      { id: crypto.randomUUID(), role: "user", content: text.trim() },
      { id: assistantId, role: "assistant", content: "" },
    ];
    setActive(id);
    if (!active) setSessions(previous => [{ id, title: text.trim(), messages: next }, ...previous]);
    else setSessions(previous => previous.map(session => session.id === id ? { ...session, messages: next } : session));
    let content = "";
    let conversationId = sessions.find(session => session.id === id)?.conversationId;
    try {
      const result = await sendChatMessage(text.trim(), conversationId, chunk => {
        content += chunk;
        updateAssistant(id, assistantId, message => ({ ...message, content }));
      }, idFromServer => {
        conversationId = idFromServer;
        setSessions(previous => previous.map(session => session.id === id ? { ...session, conversationId: idFromServer } : session));
      }, setApproval, trace => receiveTrace(id, assistantId, trace), setClarification);
      if (!content && !result.approval && !result.clarification) throw new Error("Empty response");
    } catch {
      const reconciled = conversationId ? await reconcileSavedState(id, conversationId) : false;
      if (!content && !reconciled) {
        updateAssistant(id, assistantId, message => ({ ...message, content: "The response was interrupted. Check saved request status before retrying." }));
      }
      setError("Couldn’t confirm the response. Saved status was refreshed where available; review it before retrying.");
    } finally {
      sending.current = false;
      setBusy(false);
      focusComposer();
    }
  }

  const renderSidebar = (mobile = false) => (
    <SidebarNav
      fill
      workspaceName="Agent workspace"
      disabled={busy}
      activeId={active}
      recents={sessions.map(session => ({ id: session.id, label: session.title }))}
      onToolRegistry={() => { setNavigationOpen(false); setRegistryOpen(true); }}
      onNewChat={newChat}
      onPick={selectSession}
      className="py-3"
      onCollapse={mobile ? () => setNavigationOpen(false) : undefined}
    />
  );

  return (
    <div className="chat-shell flex h-dvh bg-background text-foreground">
      <a href="#conversation" className="sr-only z-50 rounded-md bg-primary p-3 text-primary-foreground focus:not-sr-only focus:fixed focus:left-4 focus:top-4">Skip to conversation</a>
      <div className="hidden shrink-0 border-r bg-card md:block">{renderSidebar()}</div>
      <Dialog open={navigationOpen} onOpenChange={setNavigationOpen}>
        <DialogContent showCloseButton={false} className="inset-y-0 left-0 h-dvh w-64 translate-x-0 translate-y-0 gap-0 rounded-none p-0 sm:rounded-none">
          <DialogTitle className="sr-only">Workspace navigation</DialogTitle>
          <DialogDescription className="sr-only">Start a chat or open a conversation from this visit.</DialogDescription>
          {renderSidebar(true)}
        </DialogContent>
      </Dialog>
      <ToolRegistry open={registryOpen} onOpenChange={setRegistryOpen} />
      <main id="conversation" tabIndex={-1} className="flex min-w-0 flex-1 flex-col outline-none">
        <header className="flex h-14 shrink-0 items-center justify-between border-b px-4 md:px-6">
          <div className="flex min-w-0 items-center gap-2">
            <Button variant="ghost" size="icon" className="md:hidden" aria-label="Open navigation" onClick={() => setNavigationOpen(true)}><Menu size={18} /></Button>
            <MessageSquare size={16} className="hidden text-muted-foreground md:block" />
            <span className="max-w-64 truncate text-sm font-medium">{sessions.find(session => session.id === active)?.title ?? "New conversation"}</span>
          </div>
          <Button variant="ghost" size="sm" aria-label="New chat" disabled={busy} onClick={newChat}><Plus size={16} /><span className="hidden sm:inline">New chat</span></Button>
        </header>
        {messages.length === 0 ? (
          <div className="flex min-h-0 flex-1 flex-col items-center justify-center overflow-y-auto px-6 py-8">
            <div className="w-full max-w-2xl">
              <h1 className="text-2xl font-medium sm:text-3xl">A conversation to work from</h1>
              <p className="mt-3 max-w-md text-sm leading-6 text-muted-foreground">Search knowledge, inspect request status, or work with PayPal invoices and sales. Review tool activity as you go.</p>
              <div className="mt-8 flex flex-wrap gap-2" aria-label="Suggested prompts">
                {starters.map(({ icon: Icon, title, prompt }) => (
                  <Button key={title} variant="outline" size="sm" className="font-normal shadow-none" onClick={() => prepareDraft(prompt)}><Icon size={14} className="text-muted-foreground" />{title}<ArrowUpRight size={12} className="text-muted-foreground" /></Button>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <Conversation>
            <ConversationContent className="mx-auto w-full max-w-3xl gap-8 px-6 py-8 md:px-8">
              <h1 className="sr-only">Conversation</h1>
              {messages.map(message => (
                <article key={message.id} aria-label={message.role === "assistant" ? "Assistant response" : "Your message"} className={message.role === "user" ? "ml-auto max-w-[90%] rounded-2xl border border-border bg-card px-4 py-3 text-sm" : "w-full text-sm leading-7"}>
                  {message.role === "assistant" && <ToolTraces traces={message.traces ?? []} busy={busy && message.id === messages.at(-1)?.id} />}
                  {message.content ? message.role === "user" ? <p className="whitespace-pre-wrap break-words">{message.content}</p> : <MessageResponse isAnimating={busy && message.id === messages.at(-1)?.id}>{message.content}</MessageResponse> : busy ? <div role="status" className="flex items-center gap-2 text-sm text-muted-foreground"><span className="size-2 animate-pulse rounded-full bg-foreground/40" />Thinking…</div> : <p className="text-muted-foreground">{clarification ? "Waiting for your answers below." : approval ? "Waiting for your approval below." : "No response received. Retry your message."}</p>}
                  {message.role === "assistant" && message.content && !busy && <Button variant="ghost" size="icon-sm" className="mt-2 text-muted-foreground" aria-label={copied === message.id ? "Copied" : "Copy response"} title={copied === message.id ? "Copied" : "Copy response"} onClick={() => copyMessage(message)}>{copied === message.id ? <Check size={13} /> : <Copy size={13} />}</Button>}
                </article>
              ))}
            </ConversationContent>
            <ConversationScrollButton />
          </Conversation>
        )}
        <div ref={composer} className="mx-auto w-full max-w-3xl shrink-0 px-4 pb-4 pt-3 md:px-8 md:pb-6">
          {error && <div role="alert" className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-xs"><span className="min-w-0 flex-1">{error}</span>{pendingStatusError ? <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => { setError(""); setPendingStatusError(false); setStatusRetry(value => value + 1); }}>Retry status</Button> : <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => { const last = [...messages].reverse().find(message => message.role === "user"); if (last) prepareDraft(last.content); setError(""); }}>Edit & retry</Button>}<Button variant="ghost" size="icon" className="size-7" aria-label="Dismiss error" onClick={() => setError("")}><X size={13} /></Button></div>}
          {clarification && <div className="mb-4 max-h-[60dvh] overflow-y-auto p-1"><ClarificationCard key={clarification.clarification_id} questions={clarification.questions} disabled={busy || restoring} onSubmitted={answerQuestions} /></div>}
          {approval && <div className="mb-3 max-h-[60dvh] overflow-y-auto p-1"><ApprovalCard key={approval.approval_id} approval={approval} disabled={busy || restoring} onSubmit={decide} /></div>}
      <PromptBar key={seed.version} disabled={busy || restoring || !!approval || !!clarification} initialDraft={seed.text} placeholder={busy ? "Waiting for a response…" : "Give your agent a task"} onSend={send} />
          <p className="mt-3 text-center text-xs leading-4 text-muted-foreground">Conversations are saved locally on the server. Check important information.</p>
          <span role="status" className="sr-only">{busy ? "Generating response" : messages.length ? "Response finished" : "Ready"}{copied ? ". Response copied" : ""}</span>
        </div>
      </main>
    </div>
  );
}
