import type { Source } from "../api";

const ORIGIN_CLASS: Record<Source["origin"], string> = {
  internal_kb: "badge-kb",
  public_web: "badge-web",
  customer_account: "badge-account",
};

/** Snippets are raw markdown from the knowledge base; show them as plain text. */
function plainText(markdown: string): string {
  return markdown
    .replace(/\[([^\]]+)\]\([^)]*(\)|$)/g, "$1") // also links cut off by snippet truncation
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/^\s*(#+|[-*])\s+/gm, "")
    .replace(/\s+/g, " ")
    .trim();
}

export function Sources({ sources, highlighted }: { sources: Source[]; highlighted: string | null }) {
  if (sources.length === 0) return null;
  return (
    <details className="sources" open>
      <summary>
        {sources.length} source{sources.length === 1 ? "" : "s"}
      </summary>
      <ol>
        {sources.map((source) => (
          <li
            key={source.evidence_id}
            id={`src-${source.evidence_id}`}
            className={highlighted === source.evidence_id ? "source highlighted" : "source"}
          >
            <div className="source-head">
              <span className="source-id">{source.evidence_id}</span>
              <span className={`badge ${ORIGIN_CLASS[source.origin]}`}>{source.label}</span>
            </div>
            <div className="source-title">
              {source.url && source.origin === "public_web" ? (
                <a href={source.url} target="_blank" rel="noopener noreferrer nofollow">
                  {source.title}
                </a>
              ) : (
                source.title
              )}
            </div>
            {source.section && <div className="source-section">{source.section}</div>}
            {source.origin !== "customer_account" && <blockquote>{plainText(source.snippet)}</blockquote>}
          </li>
        ))}
      </ol>
    </details>
  );
}
