// Filing (D23, D25): the partner release, both clients' 8879, transmission and the agency's answer,
// the freeze, amending on top, the extension and the deadlines. Every state here comes from the server.
import { useApi } from "../api.js";
import { ErrorBox, Estimate, Loading, Ref } from "../components/common.jsx";
import { ActionBar, useCan } from "../components/Act.jsx";
import { AmendForm, TransmitForm } from "../components/Forms.jsx";
import { date, dateTime, money } from "../format.js";

const JURISDICTIONS = { federal: "Federal", california: "California" };

export default function Filing({ names, refreshKey }) {
  const { data, error } = useApi("/api/filing", refreshKey);
  const can = useCan();
  if (error) return <ErrorBox error={error} />;
  if (!data) return <Loading />;
  const tip = data.meta.tip;
  const balance = data.presented.estimated_balance_due;

  return (
    <div className="page narrow">
      <div className="page-head">
        <div>
          <h1>Filing</h1>
          <p className="muted">
            Helen releases the return, both clients sign the 8879, then someone transmits. The agency answers from the
            packet's own records. It reads the SSNs on the return, not the checker's findings.
          </p>
        </div>
        <div className="card stage">
          <span className="muted small">Where it stands</span>
          <strong>{data.stage}</strong>
        </div>
      </div>

      {data.frozen && (
        <div className="callout">
          <strong>Filed and frozen.</strong> Nothing that changes the return is accepted until an amendment opens. Notes,
          questions and evidence still append.
        </div>
      )}
      {data.amendment_open && (
        <div className="callout warn">
          <strong>Amendment open</strong> ({names[data.amendment.by] || data.amendment.by}, {dateTime(data.amendment.at)}):{" "}
          {data.amendment.reason}
        </div>
      )}

      <section className="card">
        <h2>Before it can go</h2>
        <ul className="gate">
          <Gate ok={data.release.current}
                label={data.release.current ? `Partner release by ${names[data.release.by] || data.release.by}, ${dateTime(data.release.at)}` : data.release.why} />
          {Object.entries(data.form_8879.signers).map(([id, s]) => (
            <Gate key={id} ok={s.current} label={
              s.current ? `${s.name} signed the 8879, ${dateTime(s.at)}`
                : s.signed ? `${s.name} signed an earlier version (${dateTime(s.at)}); the return changed since`
                : `${s.name} has not signed the 8879`} />
          ))}
        </ul>
        <p className="small">
          The return as presented: federal {balanceWords(balance.federal)}, California {balanceWords(balance.california)}{" "}
          <Estimate />
        </p>
        <ActionBar actions={[
          { key: "transmit", label: data.next_kind === "amended" ? "Transmit the amended return" : "Transmit", primary: true,
            allowed: can("transmit") && !data.frozen,
            render: (done) => <TransmitForm tip={tip} kind={data.next_kind} blockers={data.transmit_blockers} onDone={done} /> },
          { key: "amend", label: "Open an amendment", allowed: can("open_amendment") && data.frozen,
            render: (done) => <AmendForm tip={tip} onDone={done} /> },
        ]} />
      </section>

      {data.comparison && (
        <section className="card">
          <h2>Amended vs filed</h2>
          <table className="lines compact">
            <thead>
              <tr><th /><th className="num">As filed</th><th className="num">Now</th><th className="num">Net change</th></tr>
            </thead>
            <tbody>
              {Object.entries(JURISDICTIONS).map(([j, label]) => (
                <tr key={j}>
                  <td>{label} balance due</td>
                  <td className="num">{money(data.comparison.balance_as_filed[j])}</td>
                  <td className="num">{money(data.comparison.balance_now[j])}</td>
                  <td className="num">{money(data.comparison.net_change[j])}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="small">
            Lines changed since filing:{" "}
            {Object.keys(data.comparison.lines_changed_since_filing).map((k) => <Ref key={k} value={`line:${k}`} />)}
            {!Object.keys(data.comparison.lines_changed_since_filing).length && <span className="muted">none yet</span>}{" "}
            <Estimate />
          </p>
        </section>
      )}

      <section>
        <h2>Transmissions and the agency's answers</h2>
        {data.transmissions.length === 0 && <p className="muted">Nothing transmitted yet.</p>}
        {data.transmissions.map((t) => (
          <Transmission key={t.event} t={t} names={names} />
        ))}
      </section>

      <section className="card">
        <h2>The extension</h2>
        <p className="small">
          {data.extension.filed_at ? `${date(data.extension.filed_at)}, ${names[data.extension.by] || data.extension.by}: ` : ""}
          {data.extension.detail}
        </p>
        <p className="small muted">
          Estimated from {data.extension.estimate.based_on_version}: federal balance{" "}
          {money(data.extension.estimate.federal.estimated_balance)}, paid {money(data.extension.estimate.federal.paid_with_form_4868)}{" "}
          ({data.extension.estimate.federal.rule}). {data.extension.note}
        </p>
      </section>

      <section className="card">
        <h2>Deadlines</h2>
        <ul className="plain small">
          {data.deadlines.map((d) => (
            <li key={d.what} className={d.passed ? "muted" : ""}>
              <strong>{date(`${d.date}T12:00:00Z`)}</strong> {d.what}{" "}
              <span className={d.passed ? "muted" : "tag"}>{d.passed ? "passed" : `${d.days_left} days`}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function Gate({ ok, label }) {
  return (
    <li className={ok ? "ok" : "todo"}>
      <span className="gate-mark">{ok ? "✓" : "○"}</span> {label}
    </li>
  );
}

export function balanceWords(v) {
  if (v > 0) return `${money(v)} to pay`;
  if (v < 0) return `${money(-v)} refund`;
  return "nothing due";
}

function Transmission({ t, names }) {
  const federal = t.answer.federal;
  const california = t.answer.california;
  return (
    <article className={`card transmission ${federal.status}`}>
      <div className="muted small">
        #{t.event} · {dateTime(t.at)} · {names[t.by] || t.by} · {t.kind === "amended" ? "amended return" : "original return"}
      </div>
      <AgencyLine label="Federal" answer={federal} />
      <AgencyLine label="California" answer={california} />
      {Object.entries(t.settlement).map(([j, s]) => (
        <div key={j} className="small settlement">
          {JURISDICTIONS[j]}: {s.kind === "refund" ? "refund" : "payment"} of {money(s.amount)} on {date(`${s.on}T12:00:00Z`)}
          {s.kind === "payment" && (s.interest > 0 || s.penalty > 0) && (
            <> plus about {money(s.interest)} interest and {money(s.penalty)} late-payment penalty <Estimate /></>
          )}
          {s.workings?.length > 0 && <div className="muted">{s.workings.join(" · ")}</div>}
        </div>
      ))}
    </article>
  );
}

function AgencyLine({ label, answer }) {
  const words = { accepted: "accepted", rejected: "rejected", not_transmitted: "held, not transmitted", filed: "filed" };
  return (
    <div className={`agency ${answer.status}`}>
      <strong>{label}: {words[answer.status] || answer.status}</strong>
      {answer.submission_id && <span className="muted small"> · submission {answer.submission_id}</span>}
      {answer.ref && <> <Ref value={answer.ref} /></>}
      {(answer.errors || []).map((e) => (
        <div key={e.code} className="small">
          <code>{e.code}</code> {e.message}
        </div>
      ))}
      {answer.note && <div className="small muted">{answer.note}</div>}
    </div>
  );
}
