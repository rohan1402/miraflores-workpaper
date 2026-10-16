// Rolling 2025 into 2026 (D30 to D33): the carryovers with their history, the assets at year end,
// and the 2026 estimates. Built from the return as filed. Carryovers are flagged, never re-estimated.
import { useApi } from "../api.js";
import { ErrorBox, Estimate, Loading, Ref } from "../components/common.jsx";
import { ActionBar, useCan } from "../components/Act.jsx";
import { PlanDecisionForm } from "../components/Forms.jsx";
import { date, dateTime, money } from "../format.js";

export default function RollForward({ names, refreshKey }) {
  const { data, error } = useApi("/api/rollforward", refreshKey);
  const { data: me } = useApi("/api/me", refreshKey);
  if (error) return <ErrorBox error={error} />;
  if (!data) return <Loading />;
  const built = data.built_from;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>2026 opening</h1>
          <p className="muted">
            What next year's preparer starts from.{" "}
            {built.filed
              ? `Built from the return as filed (event ${built.event}, ${date(built.at)}, submission ${built.submission}).`
              : built.note}{" "}
            Version {data.version}.
          </p>
        </div>
        <a className="card stage" href="/api/rollforward/export" download>
          <span className="muted small">For next year's file</span>
          <strong>Download as one file</strong>
        </a>
      </div>

      <Carryovers title="Federal carryovers" rows={data.carryovers.federal} />
      <Carryovers title="California carryovers" rows={data.carryovers.california} />

      <section>
        <h2>California depreciation that differs from federal</h2>
        <table className="lines compact">
          <thead>
            <tr><th>Asset</th><th className="num">Federal accumulated</th><th className="num">California accumulated</th><th className="num">Difference carried</th></tr>
          </thead>
          <tbody>
            {data.carryovers.california_depreciation.map((a) => (
              <tr key={a.asset}>
                <td><Ref value={`asset:${a.asset}`} /> {a.description}</td>
                <td className="num">{money(a.federal_accumulated, { cents: true })}</td>
                <td className="num">{money(a.california_accumulated, { cents: true })}</td>
                <td className="num">{money(a.difference, { cents: true })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section>
        <h2>Assets at the end of 2025</h2>
        <table className="lines compact">
          <thead>
            <tr><th>Asset</th><th>In service</th><th>Method</th><th className="num">Cost</th><th className="num">Federal accumulated</th><th className="num">California accumulated</th><th className="num">AMT difference 2025</th><th /></tr>
          </thead>
          <tbody>
            {data.assets.map((a) => (
              <tr key={a.asset} className={a.carried ? "" : "muted"}>
                <td><code>{a.asset}</code> {a.description}</td>
                <td>{a.placed_in_service}</td>
                <td className="small">{a.method}, {a.life_years} years</td>
                <td className="num">{money(a.cost)}</td>
                <td className="num">{money(a.federal_accumulated, { cents: true })}</td>
                <td className="num">{money(a.california_accumulated, { cents: true })}</td>
                <td className="num">{money(a.amt_difference_2025, { cents: true })}</td>
                <td className="small">{a.carried ? "carried to 2026" : "disposed of in 2025"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section>
        <h2>2026 estimated payments <Estimate /></h2>
        <div className="home-grid">
          <Plan title="Federal" plan={data.estimates.federal} />
          <CaliforniaPlan plan={data.estimates.california} names={names} tip={me?.tip} />
        </div>
        <h3>Known changes for 2026</h3>
        <ul className="plain small">
          {data.estimates.known_2026_changes.map((t) => <li key={t}>{t}</li>)}
        </ul>
      </section>
    </div>
  );
}

function Carryovers({ title, rows }) {
  return (
    <section>
      <h2>{title}</h2>
      <table className="lines compact">
        <thead>
          <tr>
            <th>Carryover</th><th className="num">In from 2024</th><th>By version</th><th className="num">Out to 2026</th>
            <th>Worked out on</th><th>State</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => (
            <tr key={c.key}>
              <td>{c.label}</td>
              <td className="num">{c.in_2025 === null ? "" : money(c.in_2025)}</td>
              <td className="small muted">{Object.entries(c.by_version).map(([v, x]) => `${v} ${x === null ? "none" : money(x)}`).join(" · ")}</td>
              <td className="num"><strong>{c.out_2026 === null ? "none" : money(c.out_2026)}</strong></td>
              <td className="refs">{[...c.lines.map((k) => `line:${k}`), ...c.sources].map((r) => <Ref key={r} value={r} />)}</td>
              <td className="small">
                {c.moved ? (
                  <>
                    <span className="tag warn">{c.moved.why}</span>
                    {c.moved.adjusted.length > 0 && <div className="moved">adjusted: {c.moved.adjusted.join(", ")}</div>}
                    {c.moved.open_corrections.length > 0 && (
                      <div className="moved">open corrections: {c.moved.open_corrections.join(", ")}</div>
                    )}
                  </>
                ) : (
                  <span className="muted">as the engine computed it</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function Plan({ title, plan }) {
  return (
    <div className="card">
      <h3>{title}</h3>
      <p className="small">{plan.rule}</p>
      <p className="small">
        {Math.round(plan.percent * 100)}% of 2025 total tax {money(plan.base_total_tax_2025)} = <strong>{money(plan.annual)}</strong>
      </p>
      <Schedule installments={plan.installments} />
    </div>
  );
}

// California (D32): the safe harbor is always shown; what to pay follows the firm's recorded choice.
function CaliforniaPlan({ plan, names, tip }) {
  const can = useCan();
  const chosen = plan.chosen;
  return (
    <div className="card">
      <h3>California</h3>
      <p className="small">{plan.rule}</p>
      {chosen ? (
        <div className="to-pay">
          <p className="small">
            <strong>To pay:</strong>{" "}
            {chosen.method === "projected"
              ? <>90% of projected 2026 California tax {money(chosen.projected_2026_tax)} = <strong>{money(chosen.annual)}</strong></>
              : <>the safe harbor below, <strong>{money(chosen.annual)}</strong></>}
          </p>
          {chosen.method === "projected" && <Schedule installments={chosen.installments} />}
          <p className="small muted">
            {chosen.decision} (authority: {chosen.authority}), {names[chosen.by] || chosen.by}, {dateTime(chosen.at)}.
          </p>
        </div>
      ) : (
        <p className="small"><strong>No method chosen yet.</strong> Nothing is marked as the amount to pay.</p>
      )}
      <p className="small">
        Safe harbor: {Math.round(plan.percent * 100)}% of 2025 California tax {money(plan.base_total_tax_2025)} ={" "}
        <strong>{money(plan.safe_harbor.annual)}</strong>
      </p>
      <Schedule installments={plan.safe_harbor.installments} />
      {plan.overpay_note && <p className="small warn">{plan.overpay_note}</p>}
      <ActionBar actions={[
        { key: "decide", label: chosen ? "Change the method" : "Record the method", allowed: can("judgment_call"),
          render: (done) => <PlanDecisionForm planRef={plan.plan_ref} tip={tip} onDone={done} /> },
      ]} />
    </div>
  );
}

function Schedule({ installments }) {
  return (
    <ul className="plain small">
      {installments.map((i) => (
        <li key={i.due} className={i.passed ? "muted" : ""}>
          {date(`${i.due}T12:00:00Z`)}: {money(i.amount)} {i.passed && <span className="tag">due date passed</span>}
        </li>
      ))}
    </ul>
  );
}
