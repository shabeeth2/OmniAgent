"use client";

import { useEffect, useRef, useState } from "react";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import RegistryForm from "@/components/RegistryForm";
import RegistryConnection from "@/components/RegistryConnection";
import type { RegistryEntry, ToolEffect } from "@/lib/tool-registry";

const base = process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000";
async function request(path: string, method = "GET", body?: unknown, signal?: AbortSignal) {
  const response = await fetch(`${base}/api/tool-registry${path}`, {
    method, headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(20000)]) : AbortSignal.timeout(20000),
  });
  if (!response.ok) throw new Error(response.status === 422 ? "Check the connection fields and schema, then try again." : "The registry request failed. Check the backend connection and retry.");
  return response.status === 204 ? undefined : response.json();
}

export default function ToolRegistry({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const [entries, setEntries] = useState<RegistryEntry[]>([]);
  const [section, setSection] = useState<"catalog" | "mcp" | "api">("catalog");
  const [systemTools, setSystemTools] = useState<{name: string; description: string; origin: string; executable: boolean; service?: string; version?: string; source?: string}[]>([]);
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [reload, setReload] = useState(0);
  const [editing, setEditing] = useState<RegistryEntry>();
  const [formKey, setFormKey] = useState(0);
  const form = useRef<HTMLDivElement>(null);
  const inFlight = useRef(false);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    request("", "GET", undefined, controller.signal).then(setEntries).catch(() => {
      if (!controller.signal.aborted) setError("Could not load saved connections. Check the backend and retry.");
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    request("/catalog", "GET", undefined, controller.signal).then(setSystemTools).catch(() => { if (!controller.signal.aborted) setError("Could not load the tool catalog. Restart the backend and retry."); });
    return () => controller.abort();
  }, [open, reload]);

  function update(entry: RegistryEntry) {
    setEntries(previous => previous.some(item => item.id === entry.id) ? previous.map(item => item.id === entry.id ? entry : item) : [...previous, entry]);
  }
  async function action(work: () => Promise<void>) {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setError("");
    try { await work(); }
    catch (error) { setError(error instanceof Error ? error.message : "Registry request failed."); throw error; }
    finally { inFlight.current = false; setBusy(false); }
  }
  function resetForm() { setEditing(undefined); setFormKey(key => key + 1); }
  async function save(values: Record<string, unknown>) {
    await action(async () => {
      update(await request(editing ? `/${editing.id}` : "", editing ? "PATCH" : "POST", values));
      resetForm();
    });
  }
  async function test(entry: RegistryEntry, args: Record<string, unknown>) {
    await action(async () => {
      setTesting(entry.id);
      try { update(await request(`/${entry.id}/test`, "POST", { arguments: args })); }
      finally { setTesting(null); }
    });
  }
  function edit(entry: RegistryEntry) {
    setSection(entry.kind); setEditing(entry); setFormKey(key => key + 1);
    requestAnimationFrame(() => { form.current?.scrollIntoView({ block: "nearest" }); form.current?.querySelector("input")?.focus(); });
  }
  async function remove(entry: RegistryEntry) {
    await action(async () => {
      await request(`/${entry.id}`, "DELETE");
      setEntries(previous => previous.filter(item => item.id !== entry.id));
      if (editing?.id === entry.id) resetForm();
    });
  }
  async function enable(entry: RegistryEntry, names: string[]) {
    await action(async () => { update(await request(`/${entry.id}`, "PATCH", { enabled_tools: names })); });
  }
  async function classify(entry: RegistryEntry, name: string, effect: ToolEffect) {
    await action(async () => { update(await request(`/${entry.id}`, "PATCH", { tool_effects: { ...entry.tool_effects, [name]: effect } })); });
  }
  return <Dialog open={open} onOpenChange={onOpenChange}>
    <DialogContent className="max-h-[90dvh] overflow-y-auto rounded-2xl sm:max-w-4xl">
      <DialogTitle>Tool registry</DialogTitle>
      <DialogDescription>Save a connection, test it, then choose which tools the agent may use. Tools stay disabled until you enable them.</DialogDescription>
      {error && <div role="alert" className="flex flex-wrap items-center gap-2 rounded-lg border border-destructive/40 p-3 text-sm"><span className="min-w-0 flex-1">{error}</span><Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => { setError(""); setLoading(true); setReload(value => value + 1); }}>Reload list</Button></div>}
      <div className="flex flex-col gap-6 sm:flex-row"><nav aria-label="Tool registry sections" className="flex shrink-0 gap-1 sm:w-40 sm:flex-col">{([['catalog','Tool catalog'],['mcp','MCP servers'],['api','APIs']] as const).map(([key,label]) => <Button key={key} type="button" variant={section === key ? 'secondary' : 'ghost'} aria-current={section === key ? 'page' : undefined} className="justify-start" onClick={() => { setSection(key); resetForm(); }}>{label}</Button>)}</nav><div className="min-w-0 flex-1 space-y-5">
      {section === 'catalog' ? <section aria-label="Tool catalog" className="space-y-2"><h2 className="text-sm font-medium">All tools</h2>{systemTools.map(tool => <div key={`system-${tool.name}`} className="rounded-lg border p-3"><div className="flex flex-wrap items-center gap-2 break-words text-sm font-medium"><span className="min-w-0 break-all">{tool.name}</span><span className="rounded bg-muted px-2 py-0.5 text-xs">{tool.executable ? "Executable" : "Metadata only · unavailable"}</span></div><p className="mt-1 text-xs text-muted-foreground">{[tool.service, tool.origin, tool.version].filter(Boolean).join(" · ")}</p><p className="mt-1 text-xs text-muted-foreground">{tool.description}</p></div>)}{entries.flatMap(entry => (entry.tools ?? []).filter(tool => !entry.enabled_tools.includes(tool.name)).map(tool => <div key={`${entry.id}-${tool.name}`} className="rounded-lg border p-3"><div className="flex flex-wrap items-center gap-2 break-words text-sm font-medium"><span className="min-w-0 break-all">{tool.name}</span><span className="rounded bg-muted px-2 py-0.5 text-xs">{entry.kind.toUpperCase()}</span></div><p className="mt-1 text-xs text-muted-foreground">{entry.name} · Disabled</p><p className="mt-1 text-xs text-muted-foreground">{tool.description}</p></div>))}</section> : <>
      <details open={!!editing || undefined}><summary className="cursor-pointer text-sm font-medium">{editing ? 'Edit connection' : 'Add a connection'}</summary><div ref={form} className="pt-4"><RegistryForm key={`${section}-${formKey}`} initialKind={section} entry={editing} busy={busy} onSave={save} onCancel={resetForm} /></div></details>
      <section className="space-y-4 border-t pt-4" aria-labelledby="saved-tools">
        <h2 id="saved-tools" className="text-sm font-medium">Saved connections</h2>
        {loading ? <p role="status" className="text-sm text-muted-foreground">Loading connections…</p> : !entries.some(entry => entry.kind === section) ? <p className="text-sm text-muted-foreground">No connections yet. Add one above.</p> : entries.filter(entry => entry.kind === section).map(entry => <RegistryConnection key={entry.id} entry={entry} busy={busy} testing={testing === entry.id} onTest={args => test(entry, args)} onEdit={() => edit(entry)} onRemove={() => { void remove(entry).catch(() => {}); }} onEnable={names => { void enable(entry, names).catch(() => {}); }} onEffect={(name, effect) => { void classify(entry, name, effect).catch(() => {}); }} />)}
      </section>
      </>}</div></div>
    </DialogContent>
  </Dialog>;
}
