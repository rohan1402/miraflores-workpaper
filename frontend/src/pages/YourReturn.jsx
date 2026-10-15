// The clients' return (D23): what the firm presents, both spouses' 8879, and their copy once filed.
import { useApi } from "../api.js";
import { ErrorBox, Estimate, Loading } from "../components/common.jsx";
import { ActionBar, useCan } from "../components/Act.jsx";
import { Sign8879Form } from "../components/Forms.jsx";
import { date, dateTime, money } from "../format.js";
import { balanceWords } from "./Filing.jsx";

const JURISDICTIONS = { federal: "Federal (Form 1040)", california: "California (Form 540NR)" };

export default function YourReturn({ me, refreshKey }) {
  const { data, error } = useApi("/api/client/return", refreshKey);
  const can = useCan();
  if (error) return <ErrorBox error={error} />;
  if (!data) return <Loading />;
  const copy = data.copy;

  return (
    <div className="page narrow">
      <div className="page-head">
        <div>
          <h1>Your 2025 return</h1>
          <p className="muted">
            {copy ? "Filed. This is your copy." : data.waiting_for || "Ready for you to review and sign."}
          </p>
        </div>
      </div>

      {data.rejections.length > 0 && !copy && (
        <div className="callout warn">
          The IRS turned the return back on {date(data.rejections.at(-1).at)}:{" "}
          {data.rejections.at(-1).answer.federal.errors.map((e) => e.message).join(" ")} Your tax team is fixing it; you will
          be asked to sign again.
        </div>
      )}

      <section className="card">
        <table className="lines compact">
          <thead>
            <tr><th /><th className="num">Income</th><th className="num">Total tax</th><th className="num">Paid</th><th>Result</th></tr>
          </thead>
          <tbody>
            {Object.entries(JURISDICTIONS).map(([j, label]) => (
              <tr key={j}>
                <td>{label}</td>
                <td className="num">{money(data.summary[j].agi)}</td>
                <td className="num">{money(data.summary[j].total_tax)}</td>
                <td className="num">{money(data.summary[j].payments)}</td>
                <td>{balanceWords(data.summary[j].estimated_balance_due)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="small muted">
          The result includes your tax team's changes, estimated until the software recomputes the return. <Estimate />
        </p>
        <p className="small">
          On the return: {data.people.map((p) => `${p.name} (${p.ssn})`).join(", ")}
        </p>
      </section>

      <section className="card">
        <h2>Form 8879: your e-file signatures</h2>
        <ul className="gate">
          {Object.entries(data.form_8879.signers).map(([id, s]) => (
            <li key={id} className={s.current ? "ok" : "todo"}>
              <span className="gate-mark">{s.current ? "✓" : "○"}</span>{" "}
              {s.current ? `${s.name} signed, ${dateTime(s.at)}` : s.signed ? `${s.name} signed an earlier version; please sign again` : `${s.name} has not signed`}
            </li>
          ))}
        </ul>
        <ActionBar actions={[
          { key: "sign", label: "Review and sign", primary: true, allowed: data.can_sign && can("sign_8879"),
            render: (done) => <Sign8879Form tip={data.tip} onDone={done} /> },
        ]} />
      </section>

      {copy && (
        <section className="card">
          <h2>Filed</h2>
          <p className="small">
            Accepted {dateTime(copy.at)}. Federal submission {copy.answer.federal.submission_id || "on record"}; California
            submission {copy.answer.california.submission_id || "on record"}.
          </p>
          {Object.entries(copy.settlement).map(([j, s]) => (
            <p key={j} className="small">
              {JURISDICTIONS[j]}: {s.kind === "refund" ? `a refund of ${money(s.amount)} is on its way` : `${money(s.amount)} is paid by direct debit`}
              {s.kind === "payment" && s.interest + s.penalty > 0 && (
                <> ; because it is paid after April 15, expect about {money(s.interest + s.penalty)} in interest and penalty <Estimate /></>
              )}
            </p>
          ))}
        </section>
      )}
      {me.person.role !== "client" && <p className="muted small">You are seeing the clients' page.</p>}
    </div>
  );
}
