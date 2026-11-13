const base = process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000";

export type LlmSettings = {
  llm_model: string;
  llm_base_url: string | null;
  context_budget: number;
  embedding_model: string;
  embedding_base_url: string;
  llm_api_key_configured: boolean;
  embedding_api_key_configured: boolean;
  restart_required?: boolean;
  environment_overrides?: string[];
};

async function request(method: string, body?: unknown, signal?: AbortSignal): Promise<LlmSettings> {
  const response = await fetch(`${base}/api/settings/llm`, {
    method, cache: "no-store", headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(20000)]) : AbortSignal.timeout(20000),
  });
  if (!response.ok) throw new Error(response.status === 422
    ? "Check the model settings, endpoint URLs, and context budget, then try again."
    : "Cannot access model settings. Check the backend connection and retry.");
  return response.json();
}

export function loadLlmSettings(signal?: AbortSignal) {
  return request("GET", undefined, signal);
}

export function saveLlmSettings(settings: LlmSettings, llmKey: string, embeddingKey: string, signal?: AbortSignal) {
  const { llm_model, llm_base_url, context_budget, embedding_model, embedding_base_url } = settings;
  return request("PUT", {
    llm_model, llm_base_url, context_budget, embedding_model, embedding_base_url,
    ...(llmKey ? { llm_api_key: llmKey } : {}),
    ...(embeddingKey ? { embedding_api_key: embeddingKey } : {}),
  }, signal);
}
