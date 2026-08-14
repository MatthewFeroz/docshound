import type {
  CreateRunResponse,
  DocumentPayload,
  Finding,
  Run,
  RunEvent,
  RuntimeConfig,
} from "./types";

const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim() ?? "";
export const API_BASE_URL = configuredBaseUrl.replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });

  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) message = payload.detail;
    } catch {
      // Preserve the status-based message for non-JSON responses.
    }
    throw new ApiError(message, response.status);
  }

  return response.json() as Promise<T>;
}

export const api = {
  getRuntimeConfig: () => request<RuntimeConfig>("/api/v1/config"),
  setMergeGatewayApiKey: (apiKey: string) =>
    request<RuntimeConfig>("/api/v1/config/llm-credential", {
      method: "POST",
      body: JSON.stringify({ api_key: apiKey }),
    }),
  createRun: (repo: string) =>
    request<CreateRunResponse>("/api/v1/runs", {
      method: "POST",
      body: JSON.stringify({ repo, limit: 50, dry_run: false }),
    }),
  getRun: (runId: string) => request<Run>(`/api/v1/runs/${runId}`),
  listFindings: () => request<Finding[]>("/api/v1/findings"),
  getFinding: (runId: string, index: number) =>
    request<Finding>(`/api/v1/runs/${runId}/findings/${index}`),
  approveFinding: (runId: string, index: number, markdown: string) =>
    request<DocumentPayload>(
      `/api/v1/runs/${runId}/findings/${index}/approval`,
      {
        method: "POST",
        body: JSON.stringify({ markdown }),
      },
    ),
  rejectFinding: (runId: string, index: number) =>
    request<Finding>(`/api/v1/runs/${runId}/findings/${index}/rejection`, {
      method: "POST",
      body: "{}",
    }),
  getDocument: (slug: string) =>
    request<DocumentPayload>(`/api/v1/documents/${slug}`),
  previewPullRequest: (slug: string, targetRepo: string, filePath: string) =>
    request<DocumentPayload>(`/api/v1/documents/${slug}/pull-request-preview`, {
      method: "POST",
      body: JSON.stringify({
        target_repo: targetRepo,
        file_path: filePath || null,
      }),
    }),
  createPullRequest: (slug: string) =>
    request<DocumentPayload>(`/api/v1/documents/${slug}/pull-request`, {
      method: "POST",
      body: "{}",
    }),
};

export function assetUrl(path: string): string {
  return `${API_BASE_URL}${path}`;
}

export function subscribeToRun(
  runId: string,
  onEvent: (event: RunEvent) => void,
  onError: () => void,
): () => void {
  const source = new EventSource(`${API_BASE_URL}/api/v1/runs/${runId}/events`);
  source.onmessage = (message) => {
    onEvent(JSON.parse(message.data) as RunEvent);
  };
  source.onerror = () => {
    source.close();
    onError();
  };
  return () => source.close();
}
