// Small shared pieces: state badges, reference links, loading and error boxes.
import { MACHINE, SEVERITY_LABEL, VERIFICATION_LABEL, date, initials } from "../format.js";
import { linkFor } from "../router.js";

// Machine state: a thin outlined badge. It never says "verified" (D2).
export function MachineBadge({ state }) {
  if (!state) return null;
  const m = MACHINE[state] || { label: state, tone: "muted" };
  return <span className={`badge machine tone-${m.tone}`}>{m.label}</span>;
}

// Human state: solid, with a person's initials and a date. Only a person verifies.
export function HumanBadge({ human, names }) {
  if (!human) return null;
  const who = initials(names?.[human.by] || human.by);
  if (human.state === "adjusted") return <span className="badge human adjusted" title={`Adjusted by ${names?.[human.by] || human.by}`}>Adjusted · {who}</span>;
  const type = VERIFICATION_LABEL[human.type] || human.type;
  return (
    <span className={`badge human ${human.state}`} title={`${type}, ${date(human.at)}`}>
      {human.state === "stale" ? "Verified, value since changed" : "Verified"} · {who}
    </span>
  );
}

export function SeverityDot({ severity }) {
  return <span className={`dot sev-${severity}`} title={SEVERITY_LABEL[severity]} />;
}

// Open findings, labelled: errors first (they can change the tax or block filing), then warnings and notes.
export function Counts({ counts, compact }) {
  if (!counts) return null;
  const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
  const rest = [
    counts.warning ? plural(counts.warning, "warning") : null,
    counts.info ? plural(counts.info, "note") : null,
  ].filter(Boolean);
  if (compact) {
    return counts.error ? <span className="count sev-error" title={plural(counts.error, "open error")}>{counts.error}</span> : null;
  }
  return (
    <span className="counts">
      {counts.error ? <span className="count sev-error">{plural(counts.error, "error")}</span> : <span className="no-errors">no errors</span>}
      {rest.length > 0 && <span className="count-rest">{rest.join(" · ")}</span>}
    </span>
  );
}

// A reference (line:F1040.26, D09, doc:D31#page32, qa-41 ...) as a link when there is a screen for it.
export function Ref({ value, children }) {
  const to = linkFor(value);
  const label = children || value.replace(/^line:/, "").replace(/^area:/, "");
  return to ? (
    <a className="ref" href={to}>
      {label}
    </a>
  ) : (
    <span className="ref plain">{label}</span>
  );
}

export function Loading() {
  return <div className="loading">Loading…</div>;
}

export function ErrorBox({ error }) {
  if (!error) return null;
  return <div className="error-box">{error.message}</div>;
}

export function Estimate() {
  return (
    <span className="estimate" title="The engine cannot be rerun. Tax effects use the version's per-dollar rates.">
      estimate
    </span>
  );
}
