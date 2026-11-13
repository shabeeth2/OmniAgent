"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { Settings2 } from "lucide-react";
import { Dialog, DialogContent, DialogTitle, DialogDescription, DialogTrigger } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { loadLlmSettings, saveLlmSettings, type LlmSettings as Settings } from "@/lib/llm-settings";

export default function LlmSettings() {
  const [open, setOpen] = useState(false);
  return <Dialog open={open} onOpenChange={setOpen}>
    <DialogTrigger asChild>
      <button type="button" title="Configure LLM" className="sidebar-row mx-2 mt-4 flex h-9 items-center rounded-lg px-2 text-left text-ink-2 transition-colors hover:bg-hover-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <Settings2 aria-hidden="true" className="size-5 shrink-0" />
        <span className="sidebar-copy ml-2 truncate text-sm font-medium">Configure</span>
      </button>
    </DialogTrigger>
    <DialogContent className="max-h-[90dvh] w-[calc(100%_-_2rem)] overflow-y-auto rounded-lg">
      <DialogTitle>Configure LLM</DialogTitle>
      <DialogDescription>Set up your chat model and embeddings. Settings are saved locally on this computer.</DialogDescription>
      {open && <SettingsForm />}
    </DialogContent>
  </Dialog>;
}

function SettingsForm() {
  const [settings, setSettings] = useState<Settings>();
  const [llmKey, setLlmKey] = useState("");
  const [embeddingKey, setEmbeddingKey] = useState("");
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const saving = useRef(false);
  const lifetime = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    lifetime.current = controller;
    loadLlmSettings(controller.signal).then(value => {
      if (!controller.signal.aborted) setSettings(value);
    }).catch(() => {
      if (!controller.signal.aborted) setError("Could not load model settings. Check the backend connection and retry.");
    });
    return () => controller.abort();
  }, [reload]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!settings || saving.current) return;
    saving.current = true; setBusy(true); setError(""); setSaved(false);
    try {
      const result = await saveLlmSettings(settings, llmKey, embeddingKey, lifetime.current?.signal);
      if (lifetime.current?.signal.aborted) return;
      setSettings(result); setLlmKey(""); setEmbeddingKey(""); setSaved(true);
    } catch {
      if (!lifetime.current?.signal.aborted) setError("Could not save. Check the model settings, endpoint URLs, and backend connection, then retry.");
    } finally {
      saving.current = false;
      if (!lifetime.current?.signal.aborted) setBusy(false);
    }
  }

  function update<K extends keyof Settings>(name: K, value: Settings[K]) {
    setSettings(previous => previous ? { ...previous, [name]: value } : previous);
    setSaved(false);
  }

  return <form onSubmit={submit} className="space-y-4">
    {error && <div role="alert" className="space-y-2 text-sm text-destructive"><p>{error}</p>{!settings && <Button type="button" variant="outline" size="sm" onClick={() => { setError(""); setReload(value => value + 1); }}>Retry</Button>}</div>}
    {!settings ? !error && <p role="status" className="text-sm text-muted-foreground">Loading model settings…</p> : <>
      <fieldset disabled={busy} className="space-y-3">
        <legend className="mb-3 text-sm font-medium">Chat model</legend>
        <label className="block space-y-1 text-sm"><span>Model name</span><Input required value={settings.llm_model} onChange={event => update("llm_model", event.target.value)} placeholder="your-tool-calling-model" /></label>
        <label className="block space-y-1 text-sm"><span>API base URL <span className="text-muted-foreground">(optional)</span></span><Input type="url" value={settings.llm_base_url ?? ""} onChange={event => update("llm_base_url", event.target.value)} placeholder="https://your-provider.example/v1" /></label>
        <label className="block space-y-1 text-sm"><span>API key</span><Input type="password" autoComplete="new-password" required={!settings.llm_api_key_configured} value={llmKey} onChange={event => { setLlmKey(event.target.value); setSaved(false); }} placeholder={settings.llm_api_key_configured ? "Key saved · leave blank to keep" : "Enter API key"} /></label>
        <label className="block space-y-1 text-sm"><span>Context budget <span className="text-muted-foreground">(characters)</span></span><Input type="number" min={1000} max={1000000} step={1} required value={settings.context_budget} onChange={event => update("context_budget", Number(event.target.value))} /></label>
      </fieldset>
      <fieldset disabled={busy} className="space-y-3 border-t pt-4">
        <legend className="pt-3 text-sm font-medium">Embeddings</legend>
        <p className="text-xs text-muted-foreground">Used to find tools and search documents. Use a compatible embedding endpoint with 1024 dimensions.</p>
        <label className="block space-y-1 text-sm"><span>Embedding model name</span><Input required value={settings.embedding_model} onChange={event => update("embedding_model", event.target.value)} /></label>
        <label className="block space-y-1 text-sm"><span>Embedding endpoint URL</span><Input type="url" required value={settings.embedding_base_url} onChange={event => update("embedding_base_url", event.target.value)} placeholder="https://your-provider.example/v1/embeddings" /></label>
        <label className="block space-y-1 text-sm"><span>Embedding API key</span><Input type="password" autoComplete="new-password" required={!settings.embedding_api_key_configured} value={embeddingKey} onChange={event => { setEmbeddingKey(event.target.value); setSaved(false); }} placeholder={settings.embedding_api_key_configured ? "Key saved · leave blank to keep" : "Enter API key"} /></label>
      </fieldset>
      <p className="text-xs text-muted-foreground">Saved keys are never displayed. Restart the app after saving to apply changes. Saving does not contact providers.</p>
      {!!settings.environment_overrides?.length && <p role="status" className="text-sm">Process environment variables override saved settings: {settings.environment_overrides.join(", ")}. Update or unset them before restarting.</p>}
      {(saved || settings.restart_required) && <p role="status" className="text-sm">Settings saved. Restart the app to apply them.</p>}
      <div className="flex justify-end"><Button type="submit" disabled={busy}>{busy ? "Saving…" : "Save settings"}</Button></div>
    </>}
  </form>;
}
