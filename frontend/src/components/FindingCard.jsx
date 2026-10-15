// One checker finding: what is wrong, the proof, the proposed change and its estimated effect.
import { Estimate, MachineBadge, Ref, SeverityDot } from "./common.jsx";
import { figure, money } from "../format.js";

export default function FindingCard({ finding }) {
  const f = finding;
  return (
    <article className={`finding sev-${f.severity} status-${f.status}`}>
      <header>
        <SeverityDot severity={f.severity} />
        <strong>{f.title}</strong>
        <MachineBadge state={f.kind} />
        <code className="code" title="Stable check code">
          {f.id}
        </code>
        {f.status !== "open" && (
          <span className="tag ok" title="A person answered this finding">
            {f.status} (event {f.addressed_by})
          </span>
        )}
      </header>
      <p>{f.message}</p>
      <div className="refs">
        <span className="muted small">On</span> {f.targets.map((t) => <Ref key={t} value={t} />)}
        {f.evidence.length > 0 && (
          <>
            <span className="muted small"> · proof</span> {f.evidence.map((t) => <Ref key={t} value={t} />)}
          </>
        )}
      </div>
      {f.changes.length > 0 && (
        <table className="changes">
          <tbody>
            {f.changes.map((c, i) => (
              <tr key={i}>
                <td className="key">
                  <Ref value={`line:${c.line}`} />
                </td>
                <td className="num muted">{c.from === null ? "not on return" : figure(c.from, c.line)}</td>
                <td>→</td>
                <td className="num">{c.to === null ? "removed" : figure(c.to, c.line)}</td>
                <td className="muted small">corrects {c.component}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {f.effect && (
        <div className="effect small">
          Tax effect: federal <span className="num">{signed(f.effect.federal)}</span>, California{" "}
          <span className="num">{signed(f.effect.california)}</span> <Estimate />
        </div>
      )}
    </article>
  );
}

function signed(v) {
  return `${v > 0 ? "+" : ""}${money(v)}`;
}
