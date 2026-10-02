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

export type ChatResponse = {
  reply: string;
  citations: Citation[];
  actions: string[];
  verifier: { ok: boolean; violations: string[] };
  facts: Fact[];
  events: TraceEvent[];
  mode: string;
  errors: string[];
  state: Snapshot;
};

function headers(apiKey: string): HeadersInit {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (apiKey.trim()) h["X-OpenAI-Key"] = apiKey.trim();
  return h;
}

async function post<T>(url: string, body: unknown, apiKey: string): Promise<T> {
  const res = await fetch(url, { method: "POST", headers: headers(apiKey), body: JSON.stringify(body) });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

export const newSession = (consentScenario: string, apiKey: string) =>
  post<{ session_id: string; reply: string; mode: string; state: Snapshot; events: TraceEvent[] }>(
    "/api/session",
    { consent_scenario: consentScenario },
    apiKey,
  );

export const sendMessage = (sessionId: string, message: string, apiKey: string) =>
  post<ChatResponse>("/api/chat", { session_id: sessionId, message }, apiKey);

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
  post<EvalResult>(`/api/session/${sessionId}/evaluate`, { scenario_id: scenarioId }, "");
