import type { ActivityEvent, ChatResponse } from "../api";

// Shows *what* the agent did (high-level, user-safe events), never *why* (no chain of thought).

const ICON: Record<string, string> = {
  search_knowledge_base: "📚",
  get_customer_account: "👤",
  web_search: "🌐",
};

export function ActivityPanel({
  events,
  busy,
  last,
}: {
  events: ActivityEvent[];
  busy: boolean;
  last: ChatResponse | null;
}) {
  return (
    <aside className="activity" aria-label="Agent activity">
      <h2>Agent activity</h2>
      {events.length === 0 && !busy && <p className="muted">Steps the assistant takes will appear here.</p>}
      <ol className="timeline">
        {events.map((event, i) => (
          <li key={i} className={`event event-${event.kind}`}>
            <span className="event-icon" aria-hidden>
              {event.tool ? ICON[event.tool] ?? "🔧" : event.kind === "final" ? "✅" : event.kind === "guardrail" ? "🛡️" : "💭"}
            </span>
            <span>
              {event.label}
              {event.detail && event.kind === "tool_finished" && <span className="event-detail">{event.detail}</span>}
            </span>
          </li>
        ))}
        {busy && (
          <li className="event event-pending">
            <span className="spinner" aria-hidden /> Working…
          </li>
        )}
      </ol>
      {last && !busy && (
        <dl className="stats">
          <div>
            <dt>Confidence</dt>
            <dd className={`conf conf-${last.evidence.confidence}`}>{last.evidence.confidence}</dd>
          </div>
          <div>
            <dt>Tool calls</dt>
            <dd>{last.tool_calls.length}</dd>
          </div>
          <div>
            <dt>KB searches</dt>
            <dd>{last.evidence.retrieval_attempts}</dd>
          </div>
          <div>
            <dt>Latency</dt>
            <dd>{(last.usage.latency_ms / 1000).toFixed(1)} s</dd>
          </div>
        </dl>
      )}
    </aside>
  );
}
