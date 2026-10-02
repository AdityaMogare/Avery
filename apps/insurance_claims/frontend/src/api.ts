export type Citation = { text: string; fact_ids: string[]; facts: string[] };
export type TraceEvent = { turn: number; type: string; data: Record<string, unknown> };
export type Fact = { id: string; value: string; source: string };
export type Slot = { value: unknown; turn: number };

export type Snapshot = {
  session_id: string;
  phase: string;
  turn: number;
  verification: {
    status: string;
    party_id: string | null;
    matched_fields: string[];
    failed_attempts: number;
    verified_for_claims: boolean;
  };
  consent: { required: boolean; scenario: string; status: string; polls: number };
  memory: {
    pii: Record<string, Slot>;
    policy_number: Slot | null;
    caller_role: Slot | null;
    representative_name: Slot | null;
    representative_relationship: Slot | null;
    intent: Slot | null;
    case_hints: Record<string, Slot>;
    followup_topics: Slot[];
    caller_notes: Slot[];
  };
  selected_case_id: string | null;
  candidate_case_ids: string[];
  pending_offer: string | null;
  counters: Record<string, number>;
  email: {
    offered: boolean;
    choice: string | null;
    sent_to: string | null;
    preview: null | {
      subject: string;
      greeting: string;
      discussed: string[];
      claim: Record<string, string> | null;
      next_steps: string[];
    };
  };
  discussed_topics: string[];
  transfer_reason: string | null;
};

export type TurnUsage = {
  llm_calls?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  llm_ms?: number;
  wall_ms?: number;
  cost_usd?: number;
};

export function usageLabel(u?: TurnUsage): string {
  if (!u || !u.llm_calls) return "";
  const secs = ((u.wall_ms ?? 0) / 1000).toFixed(1);
  const tokens = (u.prompt_tokens ?? 0) + (u.completion_tokens ?? 0);
  return `${secs} s · ${u.llm_calls} calls · ${tokens.toLocaleString()} tok · $${(u.cost_usd ?? 0).toFixed(4)}`;
}

export type ChatResponse = {
  reply: string;
  citations: Citation[];
  actions: string[];
  verifier: { ok: boolean; violations: string[] };
  facts: Fact[];
  events: TraceEvent[];
  mode: string;
  errors: string[];
  usage: TurnUsage;
  state: Snapshot;
};

/** Any provider's key; the backend detects the provider from the key prefix unless one is chosen. */
export type LlmCreds = { key: string; provider: string };

export const PROVIDERS = ["auto", "openai", "anthropic", "gemini", "openrouter", "groq", "xai"];

function headers(llm?: LlmCreds): HeadersInit {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (llm?.key.trim()) {
    h["X-LLM-Key"] = llm.key.trim();
    if (llm.provider !== "auto") h["X-LLM-Provider"] = llm.provider;
  }
  return h;
}

async function post<T>(url: string, body: unknown, llm?: LlmCreds): Promise<T> {
  const res = await fetch(url, { method: "POST", headers: headers(llm), body: JSON.stringify(body) });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

export const newSession = (consentScenario: string, llm: LlmCreds) =>
  post<{ session_id: string; reply: string; mode: string; state: Snapshot; events: TraceEvent[] }>(
    "/api/session",
    { consent_scenario: consentScenario },
    llm,
  );

export const sendMessage = (sessionId: string, message: string, llm: LlmCreds) =>
  post<ChatResponse>("/api/chat", { session_id: sessionId, message }, llm);

export type Scenario = {
  id: string;
  description: string;
  turns: string[];
  consent_scenario?: string;
  category?: string;
  gate?: string;
  source?: string;
  expect: Record<string, unknown>;
};

export type EvalResult = {
  scenario_id: string;
  passed: boolean;
  failures: string[];
  trace_properties: Record<string, boolean>;
};

export async function listScenarios(): Promise<Scenario[]> {
  const res = await fetch("/api/scenarios");
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return (await res.json()).scenarios as Scenario[];
}

export const evaluateSession = (sessionId: string, scenarioId: string) =>
  post<EvalResult>(`/api/session/${sessionId}/evaluate`, { scenario_id: scenarioId });
