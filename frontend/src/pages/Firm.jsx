// The firm: time against budget, the firm's standards (the administrator edits them), and the
// sensitive-data view log (partner and administrator).
import { useApi, useApp } from "../api.js";
import { ErrorBox, Loading, Ref } from "../components/common.jsx";
import { ActionBar, useCan } from "../components/Act.jsx";
import { LogTimeForm, StandardForm } from "../components/Forms.jsx";
import { dateTime } from "../format.js";

export default function Firm({ names, refreshKey }) {
  const { me } = useApp();
  const seesViewLog = ["partner", "firm_administrator"].includes(me.person.role);
  return (
    <div className="page narrow">
      <div className="page-head">
        <div>
          <h1>Firm</h1>
          <p className="muted">Time against the engagement budget, the firm's standards, and who unmasked sensitive data.</p>
        </div>
      </div>
      <Time names={names} refreshKey={refreshKey} />
      <Standards names={names} refreshKey={refreshKey} />
      {seesViewLog && <ViewLog names={names} refreshKey={refreshKey} />}
    </div>
  );
}

function Time({ names, refreshKey }) {
  const { data, error } = useApi("/api/firm/time", refreshKey);
  const { me } = useApp();
  const can = useCan();
  if (error) return <ErrorBox error={error} />;
  if (!data) return <Loading />;
  return (
    <section className="card">
      <h2>Time against budget</h2>
      <table className="lines compact">
        <thead>
          <tr><th>Budget</th><th className="num">Hours</th><th className="num">Logged</th><th className="num">Left</th><th>By</th></tr>
        </thead>
        <tbody>
          {data.buckets.map((b) => (
            <tr key={b.bucket}>
              <td>{b.bucket.replace(/_/g, " ")}</td>
              <td className="num">{b.budget}</td>
              <td className={`num ${b.over ? "flag" : ""}`}>{b.logged}</td>
              <td className="num">{b.left}</td>
              <td className="small muted">{Object.entries(b.by_person).map(([p, h]) => `${names[p] || p} ${h}`).join(", ")}</td>
            </tr>
          ))}
          <tr className="total">
            <td>Total</td><td className="num">{data.total.budget}</td><td className="num">{data.total.logged}</td>
            <td className="num">{data.total.left}</td><td />
          </tr>
        </tbody>
      </table>
      <ActionBar actions={[
        { key: "log", label: "Log time", allowed: can("log_time"),
          render: (done) => <LogTimeForm buckets={data.buckets.map((b) => b.bucket)} tip={me.tip} onDone={done} /> },
      ]} />
    </section>
  );
}

// The standards in force. Each number or list can be changed by the administrator, with a reason;
// the change is an event, so the checker uses the new value from then on and replay shows the old one.
const EDITABLE = [
  ["variance_review.flag_if_change_over_percent", "Flag a swing from last year over this percent"],
  ["variance_review.and_over_amount", "and over this many dollars"],
  ["verification_types", "Ways a person may verify a number"],
  ["rules", "Firm rules"],
  ["required_steps", "Required steps before filing"],
];

function Standards({ names, refreshKey }) {
  const { data, error } = useApi("/api/firm/standards", refreshKey);
  const { me } = useApp();
  const can = useCan();
  if (error) return <ErrorBox error={error} />;
  if (!data) return <Loading />;
  const at = (path) => path.split(".").reduce((node, part) => node?.[part], data.standards);
  return (
    <section className="card">
      <h2>Firm standards</h2>
      {EDITABLE.map(([path, label]) => {
        const value = at(path);
        return (
          <div key={path} className="standard">
            <div className="small strong">{label}</div>
            {Array.isArray(value) ? (
              <ul className="plain small">
                {value.map((v) => <li key={v}>{v.replace(/_/g, " ")}</li>)}
              </ul>
            ) : (
              <div className="num">{value}</div>
            )}
            <ActionBar actions={[
              { key: "edit", label: "Change", allowed: can("set_standard"),
                render: (done) => <StandardForm path={path} current={value} tip={me.tip} onDone={done} /> },
            ]} />
          </div>
        );
      })}
      {data.changes.length > 0 && (
        <>
          <h3>Changes</h3>
          <ul className="plain small">
            {data.changes.map((c) => (
              <li key={c.event}>
                {dateTime(c.at)} · {names[c.by] || c.by} changed <code>{c.path}</code> to{" "}
                <strong>{Array.isArray(c.value) ? `${c.value.length} entries` : String(c.value)}</strong>: {c.reason}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function ViewLog({ names, refreshKey }) {
  const { data, error } = useApi("/api/audit/sensitive-views", refreshKey);
  if (error) return <ErrorBox error={error} />;
  if (!data) return <Loading />;
  return (
    <section className="card">
      <h2>Sensitive-data view log</h2>
      <p className="small muted">Every unmasked view and every file opened. The log keeps what was opened, never the digits.</p>
      {data.length === 0 && <p className="small muted">No one has unmasked anything.</p>}
      <ul className="plain small">
        {data.slice().reverse().map((e) => (
          <li key={e.id}>
            {dateTime(e.at)} · {names[e.actor] || e.actor} opened {e.targets.map((t) => <Ref key={t} value={t} />)}
          </li>
        ))}
      </ul>
    </section>
  );
}
