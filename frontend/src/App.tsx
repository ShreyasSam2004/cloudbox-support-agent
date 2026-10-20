import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { ApiError, streamChat, type ActivityEvent, type ChatResponse } from "./api";
import { ActivityPanel } from "./components/ActivityPanel";
import { RichText } from "./components/RichText";
import { Sources } from "./components/Sources";

interface Message {
  role: "user" | "assistant" | "error";
  text: string;
  response?: ChatResponse;
}

// Demo identities. In production the customer comes from the sign-in token, not a picker.
const DEMO_CUSTOMERS: { id: string; label: string }[] = [
  { id: "", label: "Not signed in" },
  { id: "C1001", label: "C1001 · Acme Analytics (Pro)" },
  { id: "C1002", label: "C1002 · Brightline Studio (cancelled)" },
  { id: "C1003", label: "C1003 · Northwind Logistics (Business)" },
  { id: "C1004", label: "C1004 · Globex (Enterprise)" },
  { id: "C1005", label: "C1005 · Initech (locked)" },
  { id: "C1006", label: "C1006 · Umbrella Health (quota)" },
  { id: "C1007", label: "C1007 · Stark Robotics (rate limit)" },
  { id: "C1008", label: "C1008 · Hooli (trial)" },
  { id: "C1009", label: "C1009 · Pied Piper (past due)" },
  { id: "C1011", label: "C1011 · Wayne Media (annual renewal)" },
  { id: "C1012", label: "C1012 · Fernwood Bakery (duplicate)" },
];

const SUGGESTIONS = [
  "How do I reset my API key?",
  "I cancelled my subscription but was charged today. Can I get a refund?",
  "My API requests are returning 429. How do I fix this?",
  "Is SSO available on the Pro plan?",
];

const TYPE_LABEL: Record<ChatResponse["response_type"], string> = {
  answer: "Answer",
  clarification: "Needs your input",
  cannot_verify: "Couldn't verify",
};

export default function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [customerId, setCustomerId] = useState("");
  const [sessionId, setSessionId] = useState<string | undefined>();
  const [busy, setBusy] = useState(false);
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [highlight, setHighlight] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    // Block body on purpose: newer Chromium returns a Promise from scrollIntoView, and an effect must
    // not return anything other than a cleanup function.
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  const reset = (nextCustomer = customerId) => {
    abortRef.current?.abort();
    setMessages([]);
    setEvents([]);
    setSessionId(undefined);
    setCustomerId(nextCustomer);
  };

  const send = async (text: string) => {
    const message = text.trim();
    if (!message || busy) return;
    setInput("");
    setBusy(true);
    setEvents([]);
    setMessages((m) => [...m, { role: "user", text: message }]);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const response = await streamChat(
        { message, session_id: sessionId, customer_id: customerId || undefined },
        (event) => setEvents((e) => [...e, event]),
        controller.signal,
      );
      setSessionId(response.session_id);
      setEvents(response.activity);
      setMessages((m) => [...m, { role: "assistant", text: response.answer, response }]);
    } catch (err) {
      if (controller.signal.aborted) return;
      const text =
        err instanceof ApiError && err.status === 429
          ? "You're sending messages too quickly. Please wait a moment and try again."
          : "Sorry, something went wrong. Please try again.";
      setMessages((m) => [...m, { role: "error", text }]);
    } finally {
      setBusy(false);
    }
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void send(input);
  };
  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send(input);
    }
  };
  const onCite = (id: string) => {
    setHighlight(id);
    document.getElementById(`src-${id}`)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  };
  const last = [...messages].reverse().find((m) => m.response)?.response ?? null;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <img src="/favicon.svg" alt="" width={28} height={28} />
          <span>CloudBox Support</span>
        </div>
        <div className="controls">
          <label>
            <span className="sr-only">Signed-in customer (demo)</span>
            <select value={customerId} onChange={(e) => reset(e.target.value)} disabled={busy}>
              {DEMO_CUSTOMERS.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.label}
                </option>
              ))}
            </select>
          </label>
          <button type="button" className="ghost" onClick={() => reset()} disabled={busy && !abortRef.current}>
            New conversation
          </button>
        </div>
      </header>

      <main className="layout">
        <section className="chat" aria-live="polite">
          {messages.length === 0 && (
            <div className="welcome">
              <h1>How can we help?</h1>
              <p className="muted">
                Answers are grounded in CloudBox documentation and, when you're signed in, your account. Every
                answer shows its sources.
              </p>
              <div className="suggestions">
                {SUGGESTIONS.map((s) => (
                  <button key={s} type="button" onClick={() => void send(s)}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((m, i) => (
            <article key={i} className={`msg msg-${m.role}`}>
              {m.role === "assistant" && m.response ? (
                <>
                  <div className="msg-meta">
                    <span className={`type type-${m.response.response_type}`}>{TYPE_LABEL[m.response.response_type]}</span>
                    {!m.response.evidence.grounded && <span className="type type-cannot_verify">No sources</span>}
                  </div>
                  <div className="msg-body">
                    <RichText text={m.text} onCite={onCite} />
                  </div>
                  <Sources sources={m.response.sources} highlighted={highlight} />
                </>
              ) : (
                <div className="msg-body">{m.text}</div>
              )}
            </article>
          ))}
          {busy && (
            <article className="msg msg-assistant pending">
              <span className="spinner" /> {events.at(-1)?.label ?? "Working…"}
            </article>
          )}
          <div ref={endRef} />
        </section>
        <ActivityPanel events={events} busy={busy} last={last} />
      </main>

      <form className="composer" onSubmit={onSubmit}>
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Describe your question or problem…"
          rows={2}
          maxLength={4000}
          aria-label="Message"
        />
        <button type="submit" disabled={busy || !input.trim()}>
          Send
        </button>
      </form>
    </div>
  );
}
