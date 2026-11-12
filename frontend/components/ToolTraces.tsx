"use client";

import { useState } from "react";
import { ChevronDown, Search, Terminal, LoaderCircle } from "lucide-react";
import type { ToolTrace } from "@/lib/chat";

const statuses = { running: "Running", awaiting_approval: "Awaiting approval", completed: "Completed", rejected: "Rejected", failed: "Failed" };

export default function ToolTraces({ traces, busy }: { traces: ToolTrace[]; busy: boolean }) {
  const [expanded, setExpanded] = useState<{ busy: boolean; open: boolean } | null>(null);
  const [rows, setRows] = useState<Set<string>>(new Set());
  const open = expanded?.busy === busy ? expanded.open : busy || traces.some(trace => trace.status === "awaiting_approval");
  if (!traces.length) return null;
  return (
    <section aria-label="Tool trace" className="mb-4 min-w-0 text-xs">
      <button type="button" aria-expanded={open} onClick={() => setExpanded({ busy, open: !open })} className="flex items-center gap-1.5 rounded-md px-1 py-1 text-muted-foreground hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring">
        <ChevronDown size={12} className={open ? "" : "-rotate-90"} />
        <span>{traces.length} tool {traces.length === 1 ? "call" : "calls"}{busy ? " · Working" : " · View trace"}</span>
      </button>
      {open && <div className="mt-1 space-y-1">
        {traces.map(trace => {
          const rowOpen = rows.has(trace.id);
          const Icon = trace.status === "running" ? LoaderCircle : trace.tool_name === "discover_tools" ? Search : Terminal;
          return <div key={trace.id}>
            <button type="button" aria-expanded={rowOpen} onClick={() => setRows(current => { const next = new Set(current); if (next.has(trace.id)) next.delete(trace.id); else next.add(trace.id); return next; })} className="group flex w-full min-w-0 items-center gap-2 rounded-md px-1 py-1 text-left hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring">
              <span className="relative flex size-4 shrink-0 items-center justify-center text-muted-foreground">
                <Icon size={13} className={`${trace.status === "running" ? "animate-spin motion-reduce:animate-none" : ""} ${rowOpen ? "opacity-0" : "group-hover:opacity-0 group-focus-visible:opacity-0"}`} />
                <ChevronDown size={12} className={`absolute ${rowOpen ? "" : "-rotate-90 opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100"}`} />
              </span>
              <span className="min-w-0 truncate font-medium">{trace.tool_name === "discover_tools" ? "Discover tools" : trace.tool_name}</span>
              <span className="min-w-0 truncate rounded-md bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">{statuses[trace.status]}</span>
              {trace.duration_ms != null && <span className="ml-auto shrink-0 tabular-nums text-muted-foreground">{(trace.duration_ms / 1000).toFixed(2)}s</span>}
            </button>
            {rowOpen && <div className="my-1 ml-3 space-y-2 border-l pl-3 text-muted-foreground">
              {trace.catalog_version && <p>Catalog version: {trace.catalog_version}</p>}
              {trace.arguments && <div><p className="mb-1 font-medium">Arguments</p><pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted p-2 font-mono text-[11px] leading-5">{trace.arguments}</pre></div>}
              {trace.result && <div><p className="mb-1 font-medium">{trace.status === "failed" ? "Error" : "Result"}</p><pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted p-2 font-mono text-[11px] leading-5">{trace.result}</pre></div>}
              {!trace.result && <p role="status">{statuses[trace.status]}</p>}
            </div>}
          </div>;
        })}
      </div>}
    </section>
  );
}
