// One checker finding: what is wrong, the proof, the proposed change and its estimated effect.
import { Estimate, MachineBadge, Ref, SeverityDot } from "./common.jsx";
import { ActionBar, useCan } from "./Act.jsx";
import { AdjustForm, AttachForm, DispositionForm, JudgmentForm, NoteForm, QuestionForm } from "./Forms.jsx";
import { figure, money } from "../format.js";

export default function FindingCard({ finding, tip }) {
  const f = finding;
  const can = useCan();
  // The fix the card offers comes from the server: a new figure for a line, or a line to add (a missing lot).
  const fix = f.fix;
  const open = f.status === "open" && tip !== undefined;
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
                <td className="muted small">
                  corrects {c.component}
                  {c.counted_in && (
                    <span className="tag" data-finding={c.counted_in}>
                      counted in “{c.counted_in_title}”
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {f.effect && (
        <div className="effect small">
          Tax effect: federal <span className="num">{signed(f.effect.federal)}</span>, California{" "}
          <span className="num">{signed(f.effect.california)}</span> <Estimate />
          {f.status !== "open" && <span className="muted"> · not in the total ({f.status})</span>}
        </div>
      )}
      {f.shared.map((s, i) => (
        // The same dollars found by two checks: shown once, in the finding that found them first.
        <div key={i} className="effect small shared">
          Tax effect: the same {sharedAmount(s.effect)} on {s.line} is already counted in{" "}
          <span className="strong" data-finding={s.counted_in}>
            “{s.counted_in_title}”
          </span>{" "}
          ({s.line}). Not added again.
        </div>
      ))}
      {f.details.page_dispositioned_by && (
        // The page is named; the line it prints is not on the return yet, so its dollars still count.
        <div className="small">
          Page recorded as partial (event {f.details.page_dispositioned_by}). The line it prints is still missing from
          the return: add it with an adjustment, or accept leaving it off.
        </div>
      )}
      {f.details.disposition_names && (
        // D19: a disposition answers the finding only when it names the document the checker named.
        <div className="small warn">
          The disposition on file names {f.details.disposition_names}; the checker found{" "}
          {f.answer.of || f.answer.by}. It does not answer this finding.
        </div>
      )}
      {open && (
        <ActionBar
          actions={[
            {
              // A document finding has no figure to fix: its answer is the disposition on the document (D20).
              key: "dispose", label: "Record the disposition", primary: true, allowed: Boolean(f.answer) && can("disposition"),
              render: (done) => <DispositionForm doc={f.answer.document} suggestion={f.answer} tip={tip} onDone={done} />,
            },
            {
              key: "fix", label: "Fix with an adjustment", primary: true, allowed: Boolean(fix) && can("adjust"),
              render: (done) => <AdjustForm line={fix.line} current={fix.from} suggested={fix.to} adds={fix.adds} finding={f.id}
                                            tip={tip} onDone={done} />,
            },
            {
              key: "accept", label: "Accept as is", allowed: can("judgment_call"),
              render: (done) => <JudgmentForm finding={f.id} effect={f.effect} toPartner={f.partner_if_accepted} tip={tip} onDone={done} />,
            },
            {
              key: "note", label: "Note", allowed: can("note"),
              render: (done) => <NoteForm targets={[`finding:${f.id}`]} tip={tip} onDone={done} />,
            },
            {
              key: "ask", label: "Ask", allowed: can("question"),
              render: (done) => <QuestionForm targets={[`finding:${f.id}`, ...f.targets.slice(0, 1)]} tip={tip} onDone={done} />,
            },
            {
              key: "attach", label: "Attach evidence", allowed: can("attach_evidence"),
              render: (done) => <AttachForm targets={[`finding:${f.id}`]} tip={tip} onDone={done} />,
            },
          ]}
        />
      )}
    </article>
  );
}

function sharedAmount(effect) {
  const parts = [];
  if (effect.federal) parts.push(`${money(Math.abs(effect.federal))} federal`);
  if (effect.california) parts.push(`${money(Math.abs(effect.california))} California`);
  return parts.join(" and ");
}

function signed(v) {
  return `${v > 0 ? "+" : ""}${money(v)}`;
}
