import { Fragment, type ReactNode } from "react";

// Minimal, XSS-safe renderer for the assistant's replies: paragraphs, "-"/"*" bullets, **bold**,
// `code` and citation markers like [K1] or [K1, A1]. Everything is built as React elements; model
// output is never injected as HTML.

// `_emphasis_` only when the underscores are not inside a word, so identifiers such as
// ch_1002_1008 or rate_limit_exceeded render verbatim.
const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\[(?:[KWA]\d+)(?:,\s*[KWA]\d+)*\]|(?<![A-Za-z0-9])_[^_\n]+_(?![A-Za-z0-9]))/g;

function renderInline(text: string, onCite: (id: string) => void, keyPrefix: string): ReactNode[] {
  return text.split(INLINE).map((part, i) => {
    const key = `${keyPrefix}-${i}`;
    if (/^\*\*.+\*\*$/.test(part)) return <strong key={key}>{part.slice(2, -2)}</strong>;
    if (/^`.+`$/.test(part)) return <code key={key}>{part.slice(1, -1)}</code>;
    if (/^_.+_$/.test(part)) return <em key={key}>{part.slice(1, -1)}</em>;
    if (/^\[[KWA]\d+/.test(part)) {
      const ids = part.slice(1, -1).split(/,\s*/);
      return (
        <span key={key} className="cites">
          {ids.map((id) => (
            <button key={id} type="button" className={`cite cite-${id[0]}`} onClick={() => onCite(id)} title={`Show source ${id}`}>
              {id}
            </button>
          ))}
        </span>
      );
    }
    return <Fragment key={key}>{part}</Fragment>;
  });
}

export function RichText({ text, onCite }: { text: string; onCite: (id: string) => void }) {
  const blocks = text.split(/\n{2,}/);
  return (
    <>
      {blocks.map((block, b) => {
        const lines = block.split("\n").filter((l) => l.trim() !== "");
        const isList = lines.length > 0 && lines.every((l) => /^\s*([-*]|\d+\.)\s+/.test(l));
        if (isList) {
          return (
            <ul key={b}>
              {lines.map((line, i) => (
                <li key={i}>{renderInline(line.replace(/^\s*([-*]|\d+\.)\s+/, ""), onCite, `${b}-${i}`)}</li>
              ))}
            </ul>
          );
        }
        return (
          <p key={b}>
            {lines.map((line, i) => (
              <Fragment key={i}>
                {i > 0 && <br />}
                {renderInline(line, onCite, `${b}-${i}`)}
              </Fragment>
            ))}
          </p>
        );
      })}
    </>
  );
}
