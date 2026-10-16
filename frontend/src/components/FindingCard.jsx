// One checker finding: what is wrong, the proof, the proposed change and its estimated effect.
import { Estimate, MachineBadge, Ref, SeverityDot } from "./common.jsx";
import { ActionBar, useCan } from "./Act.jsx";
import {
  AdjustForm, AttachForm, CorrectIdentityForm, DispositionForm, JudgmentForm, NoteForm, QuestionForm,
} from "./Forms.jsx";
import { figure, money } from "../format.js";

export default function FindingCard({ finding, tip }) {
  const f = finding;
  const can = useCan();
  // The fixes come from the server, one per line still to correct (D37): the figure that applies this
  // finding's pieces on that line, or a line to add (a missing lot). A fix stores the card's estimate.
  const fixes = f.fixes || [];
  const partly = f.status === "open" && f.changes.some((c) => c.applied_by || c.moved);
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
            {f.status} (event {f.addressed_by}){f.details.accepted_with && " with the finding on the same dollars"}
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
              <tr key={i} className={c.applied_by ? "applied" : ""}>
                <td className="key">
                  <Ref value={`line:${c.line}`} />
                </td>
                <td className="num muted">{c.from === null ? "not on return" : figure(c.from, c.line)}</td>
                <td>→</td>
                <td className="num">{c.to === null ? "removed" : figure(c.to, c.line)}</td>
                <td className="muted small">
                  corrects {c.component}
                  {c.applied_by && <span className="tag ok">applied (event {c.applied_by})</span>}
                  {c.moved && f.status === "open" && (
                    <span className="tag" title="The line was adjusted, but not to the documented figure">still open on the adjusted line</span>
                  )}
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
          {partly ? "Tax effect still open" : "Tax effect"}: federal <span className="num">{signed(f.effect.federal)}</span>, California{" "}
          <span className="num">{signed(f.effect.california)}</span> <Estimate />
          {f.status !== "open" && <span className="muted"> · not in the total ({f.status})</span>}
        </div>
      )}
      {f.shared.map((s, i) => (
        // The same dollars found by two checks: shown once, in the finding that found them first, or
        // left out by the acceptance of the other one (D37).
        <div key={i} className="effect small shared">
          Tax effect: the same {sharedAmount(s.effect)} on {s.line} is already {s.accepted ? "accepted as is" : "counted"} in{" "}
          <span className="strong" data-finding={s.counted_in}>
            “{s.counted_in_title}”
          </span>{" "}
          ({s.line}). Not added again.
        </div>
      ))}
      {f.status === "open" && f.details.acceptance_changed && (
        // D37: an acceptance holds while the finding's lines show the figures it saw, like a sign-off.
        <div className="small warn">
          Accepted as is in event {f.details.acceptance_changed.event}. Since then{" "}
          {f.details.acceptance_changed.lines.join(", ")} changed, so that acceptance no longer holds: answer the finding again.
        </div>
      )}
      {f.status === "open" && f.details.page_dispositioned_by && (
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
              key: "dispose", label: "Record the disposition", primary: true,
              allowed: f.answer?.act === "disposition" && can("disposition"),
              render: (done) => <DispositionForm doc={f.answer.document} suggestion={f.answer} tip={tip} onDone={done} />,
            },
            {
              // An SSN is fixed from a document that prints it; the agency reads the digits on the return (D23).
              key: "identity", label: "Correct the number", primary: true,
              allowed: f.answer?.act === "correct_identity" && can("correct_identity"),
              render: (done) => <CorrectIdentityForm person={f.answer.person} documents={f.answer.documents} finding={f.id}
                                                     tip={tip} onDone={done} />,
            },
            ...fixes.map((fx) => ({
              key: `fix:${fx.line}`, label: fixes.length > 1 ? `Fix ${fx.line}` : "Fix with an adjustment", primary: true,
              allowed: can("adjust"),
              render: (done) => <AdjustForm line={fx.line} current={fx.from} suggested={fx.to} adds={fx.adds} finding={f.id}
                                            tip={tip} onDone={done} />,
            })),
            {
              key: "accept", label: "Accept as is", allowed: can("judgment_call"),
              render: (done) => <JudgmentForm finding={f.id} effect={f.accept_effect} toPartner={f.partner_if_accepted} tip={tip} onDone={done} />,
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
