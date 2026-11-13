"use client";

import { useState } from "react";
import { Server, Plug } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { emptySchema, parseQuerySchema, type RegistryEntry } from "@/lib/tool-registry";

export default function RegistryForm({ entry, initialKind = "mcp", busy, onSave, onCancel }: { entry?: RegistryEntry; initialKind?: "mcp" | "api"; busy: boolean; onSave: (values: Record<string, unknown>) => Promise<void>; onCancel: () => void }) {
  const [kind, setKind] = useState(entry?.kind ?? initialKind);
  const [auth, setAuth] = useState(entry?.auth_scheme ?? "none");
  const [error, setError] = useState("");
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const values = Object.fromEntries(new FormData(form));
    setError("");
    try {
      const payload: Record<string, unknown> = { ...values, kind, auth_scheme: auth };
      delete payload.schema_text;
      if (!values.api_key) delete payload.api_key;
      if (kind === "api") payload.input_schema = parseQuerySchema(String(values.schema_text));
      if (auth === "none") { payload.api_key = null; payload.auth_header = "Authorization"; }
      if (auth === "bearer") payload.auth_header = "Authorization";
      await onSave(payload);
    } catch (error) { setError((error as Error).message); }
  }
  return <form onSubmit={submit} className="space-y-4">
    <fieldset disabled={busy} className="space-y-4">
      <legend className="mb-4 text-sm font-medium">{entry ? `Edit ${entry.name}` : "Add a connection"}</legend>
      <div className="flex gap-2" aria-label="Connection type">
        <Button type="button" variant={kind === "mcp" ? "secondary" : "outline"} aria-pressed={kind === "mcp"} onClick={() => { setKind("mcp"); setAuth("none"); }}><Server size={16} />MCP server</Button>
        <Button type="button" variant={kind === "api" ? "secondary" : "outline"} aria-pressed={kind === "api"} onClick={() => { setKind("api"); setAuth("none"); }}><Plug size={16} />API</Button>
      </div>
      <label className="block space-y-2 text-sm"><span>Name</span><Input name="name" required maxLength={100} defaultValue={entry?.name} placeholder="Company knowledge" /></label>
      <label className="block space-y-2 text-sm"><span>{kind === "mcp" ? "MCP endpoint URL" : "API endpoint URL"}</span><Input name="url" type="url" required defaultValue={entry?.url} placeholder={kind === "mcp" ? "https://example.com/mcp" : "https://api.example.com/search"} /><span className="text-xs text-muted-foreground">HTTPS required except for local loopback servers. MCP supports remote Streamable HTTP; OAuth and local commands are not supported.</span></label>
      <label className="block space-y-2 text-sm"><span>Description</span><Textarea name="description" required maxLength={4000} defaultValue={entry?.description} placeholder="What this connection does and when to use it" /></label>
      {kind === "api" && <>
        <label className="block space-y-2 text-sm"><span>HTTP method</span><select name="method" defaultValue={entry?.method ?? "GET"} className="h-10 w-full rounded-lg border bg-background px-3">{["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"].map(method => <option key={method}>{method}</option>)}</select><span className="text-xs text-muted-foreground">Only GET connections can be tested and enabled. Other methods can be saved.</span></label>
        <label className="block space-y-2 text-sm"><span>Query parameter schema (JSON)</span><Textarea name="schema_text" required rows={6} className="font-mono text-xs" defaultValue={JSON.stringify(entry?.input_schema ?? emptySchema, null, 2)} /><span className="text-xs leading-5 text-muted-foreground">Declare an object with scalar properties. Example: {`{"type":"object","properties":{"q":{"type":"string"}},"required":["q"],"additionalProperties":false}`}</span></label>
      </>}
      <label className="block space-y-2 text-sm"><span>Authentication</span><select value={auth} onChange={event => setAuth(event.target.value as RegistryEntry["auth_scheme"])} className="h-10 w-full rounded-lg border bg-background px-3"><option value="none">None</option><option value="bearer">Bearer token</option>{kind === "api" && <option value="api_key">API-key header</option>}</select></label>
      {auth !== "none" && <div className="grid gap-4 sm:grid-cols-2">
        <label className="block space-y-2 text-sm"><span>{entry?.has_api_key ? "Replace credential (optional)" : "API key / token"}</span><Input name="api_key" type="password" required={!entry?.has_api_key} maxLength={8192} autoComplete="new-password" placeholder={entry?.has_api_key ? "Leave blank to keep saved credential" : "Secret value"} /></label>
        {auth === "api_key" && <label className="block space-y-2 text-sm"><span>Authentication header</span><Input name="auth_header" defaultValue={entry?.auth_header ?? "X-API-Key"} pattern="[A-Za-z0-9-]+" required maxLength={100} /></label>}
      </div>}
      <p className="text-xs leading-5 text-muted-foreground">Secrets stay on the local backend. They are stored unencrypted on disk and never returned in connection responses. Saving changes disables tools until retested.</p>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <div className="flex gap-2"><Button type="submit">{busy ? "Saving…" : entry ? "Save changes" : "Save connection"}</Button>{entry && <Button type="button" variant="ghost" onClick={onCancel}>Cancel edit</Button>}</div>
    </fieldset>
  </form>;
}
