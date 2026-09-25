/**
 * Typed client for the backend's /api/v1/demo/* routes (Demo MVP). Every call goes straight to
 * the api service's published host port — the demo voice UI is entirely client-side, no Next.js
 * server involved, so there's no cookie/CSRF story here (demo mode has none — see api/deps.py's
 * require_demo_mode).
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8010/api/v1";

export class DemoApiError extends Error {
  code: string;
  status: number;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    let code = "UNKNOWN";
    let message = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      code = body?.error?.code ?? code;
      message = body?.error?.message ?? message;
    } catch {
      // response body wasn't JSON — keep the generic message
    }
    throw new DemoApiError(response.status, code, message);
  }
  return (await response.json()) as T;
}

export type ProviderName = "gemini" | "openai";
export type ProviderStatusValue = "not_configured" | "testing" | "connected" | "invalid" | "error";

export interface ProviderStatus {
  provider: ProviderName;
  status: ProviderStatusValue;
  model: string | null;
  tested_at: string | null;
  available_models: string[];
}

export interface DemoSettings {
  hospital_name: string;
  agent_name: string;
  voice_gender: "female" | "male";
}

export interface StartCallResponse {
  call_id: string;
  greeting_text: string;
  hospital_name: string;
  agent_name: string;
  voice_gender: "female" | "male";
}

export interface TurnResponse {
  response_text: string;
  detected_language: string;
  locked_language: string;
  switched_language: boolean;
  topics: string[];
  next_action: string;
  end_call: boolean;
  summary: string | null;
}

export interface TimelineEvent {
  event_id: number;
  ts: string;
  type: string;
  data: Record<string, unknown>;
}

export const demoApi = {
  listProviders: () => request<ProviderStatus[]>("/demo/providers"),

  saveProviderKey: (provider: ProviderName, apiKey: string, model: string) =>
    request<ProviderStatus>(`/demo/providers/${provider}/key`, {
      method: "POST",
      body: JSON.stringify({ api_key: apiKey, model }),
    }),

  getSettings: () => request<DemoSettings>("/demo/settings"),

  saveSettings: (settings: DemoSettings) =>
    request<DemoSettings>("/demo/settings", { method: "PUT", body: JSON.stringify(settings) }),

  startCall: (provider: ProviderName) =>
    request<StartCallResponse>("/demo/calls", {
      method: "POST",
      body: JSON.stringify({ provider }),
    }),

  submitTurn: (callId: string, provider: ProviderName, text: string) =>
    request<TurnResponse>(`/demo/calls/${callId}/turns`, {
      method: "POST",
      body: JSON.stringify({ provider, text }),
    }),

  endCall: (callId: string) =>
    request<{ status: string }>(`/demo/calls/${callId}/end`, { method: "POST" }),

  getEvents: (callId: string) => request<TimelineEvent[]>(`/demo/calls/${callId}/events`),
};
