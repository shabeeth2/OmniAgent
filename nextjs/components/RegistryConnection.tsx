"use client";

import { useState } from "react";
import { Pencil, Trash2, FlaskConical } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { emptySchema, parseTestArguments, type RegistryEntry, type ToolEffect } from "@/lib/tool-registry";

export default function RegistryConnection({ entry, busy, testing, onTest, onEdit, onRemove, onEnable, onEffect }: { entry: RegistryEntry; busy: boolean; testing: boolean; onTest: (args: Record<string, unknown>) => Promise<void>; onEdit: () => void; onRemove: () => void; onEnable: (names: string[]) => void; onEffect?: (name: string, effect: ToolEffect) => void }) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const supported = entry.kind === "mcp" || entry.method === "GET";
  const schema = entry.input_schema ?? emptySchema;
  const status = testing ? "Testing…" : ({ saved: "Saved", passed: "Test passed", failed: "Test failed" }[entry.status] ?? "Saved");
  async function test(event: React.FormEvent) {
    event.preventDefault(); setError("");
    try { await onTest(entry.kind === "api" ? parseTestArguments(schema, values) : {}); }
    catch (error) { setError((error as Error).message); }
  }
  return <details className="rounded-xl border bg-card" aria-label={entry.name}><summary className="cursor-pointer px-4 py-3 text-sm font-medium">{entry.name} <span className="ml-2 text-xs font-normal text-muted-foreground">{status} · {entry.tools?.length ?? 0} tools</span></summary><article className="space-y-3 border-t p-4">
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0 space-y-1"><h3 className="break-words text-sm font-medium">{entry.name}</h3><p className="break-all text-xs text-muted-foreground">{entry.kind === "mcp" ? "MCP · Streamable HTTP" : `API · ${entry.method}`} · {entry.url}</p></div>
      <div className="flex shrink-0"><Button type="button" variant="ghost" size="icon-sm" disabled={busy} aria-label={`Edit ${entry.name}`} onClick={onEdit}><Pencil size={14} /></Button><Button type="button" variant="ghost" size="icon-sm" disabled={busy} aria-label={`Remove ${entry.name}`} onClick={onRemove}><Trash2 size={14} /></Button></div>
    </div>
    <p className="break-words text-sm text-muted-foreground">{entry.description}</p>
    <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground"><span role="status">{status}</span>{entry.has_api_key && <span>Credential configured</span>}{entry.tested_at && <span>Last test: {new Date(entry.tested_at).toLocaleString()}</span>}</div>
    {entry.error && <p role="alert" className="text-sm text-destructive">{entry.error}</p>}
    {!supported ? <p className="text-xs text-muted-foreground">Execution not supported yet. Only GET API connections can be tested and enabled.</p> : <form onSubmit={test} className="space-y-3">
      {entry.kind === "api" && schema.required.length > 0 && <p className="text-xs text-muted-foreground">This API declares required query parameters. Enter sample values to test the request; the agent supplies them when using the tool.</p>}
      {entry.kind === "api" && Object.entries(schema.properties).length > 0 && <fieldset disabled={busy} className="space-y-3"><legend className="mb-2 text-xs font-medium">Test query parameters</legend>{Object.entries(schema.properties).map(([name, property]) => <label key={name} className="block space-y-1 text-xs"><span>{name}{schema.required.includes(name) ? " (required)" : " (optional)"}</span>{property.type === "boolean" ? <select className="h-9 w-full rounded-lg border bg-background px-3" required={schema.required.includes(name)} value={values[name] ?? ""} onChange={event => setValues(previous => ({ ...previous, [name]: event.target.value }))}><option value="">Not supplied</option><option value="true">True</option><option value="false">False</option></select> : <Input type={property.type === "string" ? "text" : "number"} step={property.type === "integer" ? "1" : "any"} required={schema.required.includes(name)} value={values[name] ?? ""} onChange={event => setValues(previous => ({ ...previous, [name]: event.target.value }))} />}{property.description && <span className="text-muted-foreground">{property.description}</span>}</label>)}</fieldset>}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <Button type="submit" variant="outline" size="sm" disabled={busy}><FlaskConical size={14} />{testing ? "Testing…" : "Test connection"}</Button>
      <p className="text-xs text-muted-foreground">{entry.kind === "mcp" ? "Connects and discovers tools without executing them." : "Sends a GET request with these arguments. The response body is not displayed."}</p>
    </form>}
    {!!entry.tools?.length && <div className="space-y-3 border-t pt-3"><p className="text-xs font-medium">{entry.tools.length} discovered {entry.tools.length === 1 ? "tool" : "tools"}</p>{entry.tools.map(tool => <div key={tool.name} className="space-y-2"><label className="flex items-start gap-3 text-sm"><input type="checkbox" role="switch" className="mt-1 size-4 accent-neutral-300" disabled={busy || entry.status !== "passed" || !supported} checked={entry.enabled_tools?.includes(tool.name) ?? false} onChange={event => onEnable(event.target.checked ? [...(entry.enabled_tools ?? []), tool.name] : (entry.enabled_tools ?? []).filter(name => name !== tool.name))} /><span className="min-w-0"><span className="block break-all font-medium">{tool.name}</span><span className="block break-words text-xs text-muted-foreground">{tool.description}</span><span className="block text-xs text-muted-foreground">{entry.enabled_tools?.includes(tool.name) ? "Enabled for agent" : "Not enabled"}</span></span></label>{entry.kind === "mcp" ? <label className="ml-7 block space-y-1 text-xs"><span>Local effect classification</span><select aria-label={`Effect of ${tool.name}`} className="h-9 w-full rounded-lg border bg-background px-3" disabled={busy || !onEffect} value={entry.tool_effects?.[tool.name] ?? "unknown"} onChange={event => onEffect?.(tool.name, event.target.value as ToolEffect)}><option value="unknown">Unknown · approval required</option><option value="read">Read-only · runs automatically</option><option value="write">Write / modify · approval required</option></select><span className="block text-muted-foreground">Only mark read-only when you trust that the tool does not change data. Server hints do not bypass approval.</span></label> : <p className="ml-7 text-xs text-muted-foreground">Read-only GET · runs automatically</p>}<details className="pl-7 text-xs text-muted-foreground"><summary className="cursor-pointer">Argument schema</summary><pre className="mt-2 max-h-48 overflow-auto rounded-lg border bg-background p-3">{JSON.stringify(tool.input_schema, null, 2)}</pre></details></div>)}</div>}
  </article></details>;
}
