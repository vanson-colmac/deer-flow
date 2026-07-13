import { getBackendBaseURL } from "../config";
import { isStaticWebsiteOnly } from "../static-mode";

import type { Model, ModelsResponse } from "./types";

const STATIC_MODELS_RESPONSE: ModelsResponse = {
  models: [],
  token_usage: { enabled: false },
};

export async function loadModels(): Promise<ModelsResponse> {
  if (isStaticWebsiteOnly()) {
    return STATIC_MODELS_RESPONSE;
  }

  const res = await fetch(`${getBackendBaseURL()}/api/models`);
  const data = (await res.json()) as Partial<ModelsResponse>;
  return {
    models: data.models ?? [],
    token_usage: data.token_usage ?? { enabled: false },
  };
}

// ---------------------------------------------------------------------------
// CRUD operations for model management
// ---------------------------------------------------------------------------

export interface ModelCreatePayload {
  name: string;
  model: string;
  display_name?: string | null;
  description?: string | null;
  use?: string;
  api_key?: string | null;
  base_url?: string | null;
  supports_thinking?: boolean;
  supports_reasoning_effort?: boolean;
  request_timeout?: number | null;
  max_retries?: number | null;
}

export interface ModelUpdatePayload {
  model?: string;
  display_name?: string | null;
  description?: string | null;
  use?: string;
  api_key?: string | null;
  base_url?: string | null;
  supports_thinking?: boolean;
  supports_reasoning_effort?: boolean;
  request_timeout?: number | null;
  max_retries?: number | null;
}

export async function createModel(payload: ModelCreatePayload): Promise<Model> {
  const { fetch: authFetch } = await import("@/core/api/fetcher");
  const res = await authFetch(`${getBackendBaseURL()}/api/models`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Failed to create model");
  }
  return res.json() as Promise<Model>;
}

export async function updateModel(
  modelName: string,
  payload: ModelUpdatePayload,
): Promise<Model> {
  const { fetch: authFetch } = await import("@/core/api/fetcher");
  const res = await authFetch(
    `${getBackendBaseURL()}/api/models/${encodeURIComponent(modelName)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Failed to update model");
  }
  return res.json() as Promise<Model>;
}

export async function deleteModel(modelName: string): Promise<void> {
  const { fetch: authFetch } = await import("@/core/api/fetcher");
  const res = await authFetch(
    `${getBackendBaseURL()}/api/models/${encodeURIComponent(modelName)}`,
    { method: "DELETE" },
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Failed to delete model");
  }
}
