const FASTAPI_BASE_URL = process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000";

export type ApprovalCall = { tool_name: string; origin: "api" | "mcp" | "simulated" | "local"; tool_call_id: string; arguments: unknown };
export type ApprovalDecision = { tool_call_id: string; decision: "approve" | "reject" };
export type Approval = { run_id: string; approval_id: string } & (ApprovalCall | { calls: ApprovalCall[] });
export type ApprovalSubmission = "approve" | "reject" | ApprovalDecision[];
export type ClarificationQuestion = { id: string; q: string; type: "radio" | "check"; options: string[] };
export type ClarificationAnswer = { question_id: string; selected: number[]; custom: string; skipped: boolean };
export type Clarification = { run_id: string; clarification_id: string; questions: ClarificationQuestion[] };
export type ToolTrace = { catalog_version?: string | null; id: string; call_id: string; tool_name: string; status: "running" | "awaiting_approval" | "completed" | "rejected" | "failed"; arguments?: string | null; result?: string | null; duration_ms?: number | null };
export type SavedMessage = { id: number; role: "user" | "assistant"; content: string; traces?: ToolTrace[] };

export async function getSavedConversationState(id: number) {
  const [response, approval, clarification] = await Promise.all([
    fetch(`${FASTAPI_BASE_URL}/api/conversations/${id}`),
    getPendingApproval(id),
    getPendingClarification(id),
  ]);
  if (!response.ok) throw new Error("Cannot load saved conversation");
  const saved: { messages: SavedMessage[] } = await response.json();
  return { messages: saved.messages, approval, clarification };
}

export async function getPendingApproval(id: number): Promise<Approval | null> {
  const response = await fetch(`${FASTAPI_BASE_URL}/api/conversations/${id}/pending-approval`);
  if (!response.ok) throw new Error("Cannot load pending approval");
  return response.json();
}

export async function getPendingClarification(id: number): Promise<Clarification | null> {
  const response = await fetch(`${FASTAPI_BASE_URL}/api/conversations/${id}/pending-clarification`);
  if (!response.ok) throw new Error("Cannot load pending questions");
  return response.json();
}

export async function sendChatMessage(
  message: string,
  conversationId?: number,
  onChunk?: (chunk: string) => void,
  onConversation?: (id: number) => void,
  onApproval?: (approval: Approval) => void,
  onTrace?: (trace: ToolTrace) => void,
  onClarification?: (clarification: Clarification) => void,
) {
  const response = await fetch(`${FASTAPI_BASE_URL}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, conversation_id: conversationId }),
    signal: AbortSignal.timeout(60000),
  });
  return consumeChat(response, conversationId, onChunk, onConversation, onApproval, onTrace, onClarification);
}

export async function resumeApproval(conversationId: number, approvalId: string, decision: ApprovalSubmission, onChunk: (chunk: string) => void, onApproval: (approval: Approval) => void, onTrace?: (trace: ToolTrace) => void, onClarification?: (clarification: Clarification) => void) {
  const response = await fetch(`${FASTAPI_BASE_URL}/api/conversations/${conversationId}/approvals/${encodeURIComponent(approvalId)}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(Array.isArray(decision) ? { decisions: decision } : { decision }), signal: AbortSignal.timeout(60000),
  });
  return consumeChat(response, conversationId, onChunk, undefined, onApproval, onTrace, onClarification);
}

export async function resumeClarification(conversationId: number, clarificationId: string, answers: ClarificationAnswer[], onChunk: (chunk: string) => void, onClarification: (clarification: Clarification) => void, onApproval?: (approval: Approval) => void, onTrace?: (trace: ToolTrace) => void) {
  const response = await fetch(`${FASTAPI_BASE_URL}/api/conversations/${conversationId}/clarifications/${encodeURIComponent(clarificationId)}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ answers }), signal: AbortSignal.timeout(60000),
  });
  return consumeChat(response, conversationId, onChunk, undefined, onApproval, onTrace, onClarification);
}

async function consumeChat(response: Response, conversationId?: number, onChunk?: (chunk: string) => void, onConversation?: (id: number) => void, onApproval?: (approval: Approval) => void, onTrace?: (trace: ToolTrace) => void, onClarification?: (clarification: Clarification) => void) {
  if (!response.ok) throw new Error(`HTTP error: ${response.status}`);
  if (!response.body) throw new Error("No response body");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = "";
  let content = "";
  let id = conversationId;
  let approval: Approval | undefined;
  let clarification: Clarification | undefined;
  try {
    while (true) {
      const part = await reader.read();
      if (part.done) throw new Error("Response ended before completion");
      pending += decoder.decode(part.value, { stream: true });
      let newline: number;
      while ((newline = pending.indexOf("\n")) >= 0) {
        const line = pending.slice(0, newline).trimEnd();
        pending = pending.slice(newline + 1);
        if (!line.startsWith("data:")) continue;
        const data = line.slice(5).trim();
        if (data === "[DONE]") {
          if (!id) throw new Error("Missing conversation ID");
          return { conversation_id: id, message: content, approval, clarification };
        }
        const event = JSON.parse(data);
        if (event.trace) onTrace?.(event.trace);
        if (Number.isInteger(event.conversation_id) && event.conversation_id > 0) {
          id = event.conversation_id;
          onConversation?.(event.conversation_id);
        }
        if (event.approval_required) {
          approval = event.approval_required;
          onApproval?.(approval!);
        }
        if (event.clarification_required) {
          clarification = event.clarification_required;
          onClarification?.(clarification!);
        }
        if (typeof event.content === "string") {
          content += event.content;
          onChunk?.(event.content);
        }
      }
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
