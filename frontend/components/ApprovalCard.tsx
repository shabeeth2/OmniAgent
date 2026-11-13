"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import type { Approval, ApprovalDecision, ApprovalSubmission } from "@/lib/chat";

export default function ApprovalCard({ approval, disabled, onSubmit }: {
  approval: Approval;
  disabled: boolean;
  onSubmit: (submission: ApprovalSubmission) => Promise<void>;
}) {
  const [decisions, setDecisions] = useState<Record<string, ApprovalDecision["decision"]>>({});
  const batch = "calls" in approval;
  const calls = batch ? approval.calls : [approval];
  const complete = calls.length > 0 && calls.every(call => decisions[call.tool_call_id]);
  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (disabled || !complete) return;
    const values = calls.map(call => ({ tool_call_id: call.tool_call_id, decision: decisions[call.tool_call_id] }));
    void onSubmit(batch ? values : values[0].decision);
  }
  if (disabled && complete) return <details className="rounded-lg border bg-card p-3 text-sm">
    <summary className="cursor-pointer">Decisions submitted · Processing</summary>
    <ul className="mt-3 space-y-2 text-muted-foreground">{calls.map(call => <li key={call.tool_call_id}>{call.tool_name}: {decisions[call.tool_call_id]}<pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words text-xs">{JSON.stringify(call.arguments, null, 2)}</pre></li>)}</ul>
  </details>;
  return <form aria-label="Tool approval" onSubmit={submit} className="space-y-4 rounded-lg border bg-card p-4 text-sm">
    <p role="status" className="font-medium">Review {calls.length === 1 ? "tool action" : `${calls.length} tool actions`}</p>
    <p className="text-muted-foreground">Approval applies only to the listed actions. Creating a draft does not send it. Choose approve or reject for every action. No action in this review proceeds until you submit the decisions.</p>
    {calls.map((call, index) => <fieldset key={call.tool_call_id} disabled={disabled} className="space-y-3 rounded-lg border p-3">
      <legend className="px-1 font-medium">{index + 1}. {call.tool_name}</legend>
      <p className="text-xs text-muted-foreground">{call.origin === "simulated" ? "Simulated operation. No real payment or email will be sent." : `${call.origin.toUpperCase()} action. Review the arguments before continuing.`}</p>
      <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted p-3 text-xs">{JSON.stringify(call.arguments, null, 2)}</pre>
      <div className="flex flex-wrap gap-4">
        {(["approve", "reject"] as const).map(decision => <label key={decision} className="flex cursor-pointer items-center gap-2">
          <input type="radio" name={`decision-${call.tool_call_id}`} value={decision} required checked={decisions[call.tool_call_id] === decision} onChange={() => setDecisions(current => ({ ...current, [call.tool_call_id]: decision }))} className="size-4 accent-neutral-300" />
          {decision === "approve" ? "Approve" : "Reject"}
        </label>)}
      </div>
    </fieldset>)}
    <Button type="submit" disabled={disabled || !complete}>Submit decisions</Button>
  </form>;
}
