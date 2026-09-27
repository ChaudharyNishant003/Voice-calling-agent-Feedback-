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
  hospital_phone: string | null;
  escalation_sla_text: string | null;
  tts_script: "devanagari" | "roman";
}

export type VisitType = "OPD" | "IPD" | "DIAGNOSTICS" | "EMERGENCY";
export type TurnEventType = "utterance" | "silence" | "stt_error";

export interface StartCallRequest {
  provider: ProviderName;
  patient_first_name: string;
  patient_phone?: string | null;
  visit_type: VisitType;
  visit_date: string; // YYYY-MM-DD
  department?: string | null;
  doctor_name?: string | null;
  patient_age?: number | null;
}

export interface ConversationTurnResponse {
  call_id: string;
  display_text: string;
  speech_text: string;
  speech_lang: string;
  node: string;
  ended: boolean;
  call_outcome: string | null;
  escalated: boolean;
}

export interface TimelineEvent {
  event_id: number;
  ts: string;
  type: string;
  data: Record<string, unknown>;
}

export interface ResultListItem {
  call_id: string;
  started_at: string | null;
  ended_at: string | null;
  patient_first_name: string | null;
  visit_type: string;
  department: string | null;
  outcome: string | null;
  rating: number | null;
  severity_max: string | null;
  complaint_count: number;
  escalated: boolean;
}

export interface ResultDetail {
  call_id: string;
  patient_first_name: string | null;
  visit_type: string;
  visit_date: string;
  department: string | null;
  doctor_name: string | null;
  outcome: string | null;
  respondent_type: string;
  language_mode: string | null;
  rating: number | null;
  rating_inferred: boolean;
  topics: Array<Record<string, unknown>>;
  complaints: Array<Record<string, unknown>>;
  escalations: Array<Record<string, unknown>>;
  transcript: Array<{ speaker: string; text: string }>;
}

export interface Escalation {
  id: string;
  call_id: string;
  type: "standard" | "urgent";
  category: string;
  triggered_by: string;
  status: "open" | "acknowledged" | "closed";
  created_at: string;
  acknowledged_at: string | null;
}

// --- Playground (see docs/11_BUILD_PLAN.md's Demo MVP section) — every LLM-backed step response
// carries raw_text/latency_ms/input_tokens/output_tokens/model alongside its parsed fields, so
// cost/speed is part of comparing models, not just the wording.

export interface PlaygroundLanguageDetectionResult {
  detected_language: string;
  requested_language: string | null;
  raw_text: string;
  latency_ms: number;
  input_tokens: number;
  output_tokens: number;
  model: string;
}

export interface PlaygroundTopicExtractionResult {
  topics: string[];
  raw_text: string;
  latency_ms: number;
  input_tokens: number;
  output_tokens: number;
  model: string;
}

export interface PlaygroundLanguageLockResult {
  locked_language: string | null;
  consecutive_other_count: number;
  switched: boolean;
}

export interface PlaygroundTopicTrackingResult {
  topics_covered: string[];
}

export interface PlaygroundEndJudgmentResult {
  wants_to_end: boolean;
  summary: string | null;
  raw_text: string;
  latency_ms: number;
  input_tokens: number;
  output_tokens: number;
  model: string;
}

export interface PlaygroundEndCeilingResult {
  ends: boolean;
}

export interface PlaygroundResponseGenerationResult {
  response: string;
  next_action: string;
  raw_text: string;
  latency_ms: number;
  input_tokens: number;
  output_tokens: number;
  model: string;
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

  startCall: (body: StartCallRequest) =>
    request<ConversationTurnResponse>("/demo/calls", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  submitTurn: (callId: string, provider: ProviderName, type: TurnEventType, text?: string) =>
    request<ConversationTurnResponse>(`/demo/calls/${callId}/turns`, {
      method: "POST",
      body: JSON.stringify({ provider, type, text }),
    }),

  endCall: (callId: string) =>
    request<{ status: string }>(`/demo/calls/${callId}/end`, { method: "POST" }),

  getEvents: (callId: string) => request<TimelineEvent[]>(`/demo/calls/${callId}/events`),

  listResults: () => request<ResultListItem[]>("/demo/results"),

  getResultDetail: (callId: string) => request<ResultDetail>(`/demo/results/${callId}`),

  resultsExportCsvUrl: () => `${API_BASE_URL}/demo/results/export.csv`,

  listEscalations: (status?: "open" | "acknowledged" | "closed") =>
    request<Escalation[]>(`/demo/escalations${status ? `?status=${status}` : ""}`),

  acknowledgeEscalation: (escalationId: string) =>
    request<Escalation>(`/demo/escalations/${escalationId}/ack`, { method: "POST" }),

  playgroundLanguageDetection: (provider: ProviderName, model: string, patientText: string) =>
    request<PlaygroundLanguageDetectionResult>("/demo/playground/steps/language-detection", {
      method: "POST",
      body: JSON.stringify({ provider, model, patient_text: patientText }),
    }),

  playgroundTopicExtraction: (provider: ProviderName, model: string, patientText: string) =>
    request<PlaygroundTopicExtractionResult>("/demo/playground/steps/topic-extraction", {
      method: "POST",
      body: JSON.stringify({ provider, model, patient_text: patientText }),
    }),

  playgroundLanguageLock: (params: {
    detectedLanguage: string;
    requestedLanguage: string | null;
    priorLockedLanguage: string | null;
    priorStreak: number;
  }) =>
    request<PlaygroundLanguageLockResult>("/demo/playground/steps/language-lock", {
      method: "POST",
      body: JSON.stringify({
        detected_language: params.detectedLanguage,
        requested_language: params.requestedLanguage,
        prior_locked_language: params.priorLockedLanguage,
        prior_streak: params.priorStreak,
      }),
    }),

  playgroundTopicTracking: (topicsMentioned: string[], priorTopicsCovered: string[]) =>
    request<PlaygroundTopicTrackingResult>("/demo/playground/steps/topic-tracking", {
      method: "POST",
      body: JSON.stringify({
        topics_mentioned: topicsMentioned,
        prior_topics_covered: priorTopicsCovered,
      }),
    }),

  playgroundEndJudgment: (params: {
    provider: ProviderName;
    model: string;
    patientText: string;
    topicsCovered: string[];
    turnCount: number;
  }) =>
    request<PlaygroundEndJudgmentResult>("/demo/playground/steps/end-judgment", {
      method: "POST",
      body: JSON.stringify({
        provider: params.provider,
        model: params.model,
        patient_text: params.patientText,
        topics_covered: params.topicsCovered,
        turn_count: params.turnCount,
      }),
    }),

  playgroundEndCeiling: (turnCount: number, llmWantsToEnd: boolean) =>
    request<PlaygroundEndCeilingResult>("/demo/playground/steps/end-ceiling", {
      method: "POST",
      body: JSON.stringify({ turn_count: turnCount, llm_wants_to_end: llmWantsToEnd }),
    }),

  playgroundResponseGeneration: (params: {
    provider: ProviderName;
    model: string;
    patientText: string;
    lockedLanguage: string | null;
    topicsCovered: string[];
    isEnding: boolean;
  }) =>
    request<PlaygroundResponseGenerationResult>("/demo/playground/steps/response-generation", {
      method: "POST",
      body: JSON.stringify({
        provider: params.provider,
        model: params.model,
        patient_text: params.patientText,
        locked_language: params.lockedLanguage,
        topics_covered: params.topicsCovered,
        is_ending: params.isEnding,
      }),
    }),
};
