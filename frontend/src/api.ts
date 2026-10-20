// Typed client for the CloudBox Support API.

export type Origin = "internal_kb" | "public_web" | "customer_account";
export type ResponseType = "answer" | "clarification" | "cannot_verify";

export interface Source {
  evidence_id: string;
  origin: Origin;
  label: string;
  title: string;
  section: string | null;
  url: string | null;
  snippet: string;
  doc_id: string | null;
}

export interface ActivityEvent {
  kind: "thinking" | "tool_started" | "tool_finished" | "guardrail" | "final";
  label: string;
  tool: string | null;
  detail: string | null;
  at: string;
}

export interface ToolCallSummary {
  step: number;
  tool: string;
  status: string;
  latency_ms: number;
  attempts: number;
  summary: string;
  query: string | null;
}

export interface ChatResponse {
  request_id: string;
  session_id: string;
  execution_id: string;
  response_type: ResponseType;
  answer: string;
  sources: Source[];
  activity: ActivityEvent[];
  tool_calls: ToolCallSummary[];
  evidence: {
    grounded: boolean;
    confidence: "high" | "medium" | "low";
    retrieval_attempts: number;
    web_search_used: boolean;
    account_data_used: boolean;
  };
  usage: { llm_calls: number; latency_ms: number; estimated_cost_usd: number | null };
  stop_reason: string;
}

export interface ChatRequest {
  session_id?: string;
  customer_id?: string;
  message: string;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

/** POST /api/v1/chat/stream and parse Server-Sent Events (EventSource cannot POST). */
export async function streamChat(
  request: ChatRequest,
  onActivity: (event: ActivityEvent) => void,
  signal?: AbortSignal,
): Promise<ChatResponse> {
  const response = await fetch("/api/v1/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
    signal,
  });
  if (!response.ok || !response.body) {
    const body = await response.json().catch(() => ({ message: response.statusText }));
    throw new ApiError(body.message ?? "Request failed", response.status);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let boundary: number;
    while ((boundary = buffer.indexOf("\n\n")) !== -1) {
      const raw = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const event = /^event: (.*)$/m.exec(raw)?.[1];
      const data = /^data: (.*)$/m.exec(raw)?.[1];
      if (!event || data === undefined) continue;
      const payload = JSON.parse(data);
      if (event === "activity") onActivity(payload as ActivityEvent);
      else if (event === "final") return payload as ChatResponse;
      else if (event === "error") throw new ApiError(payload.message ?? "Request failed", payload.status ?? 500);
    }
  }
  throw new ApiError("The connection closed before an answer arrived.", 502);
}
