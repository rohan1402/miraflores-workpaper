// One work area (or the California lens): its lines, 2024 beside 2025, machine and human states.
// Brokerage lots collapse into one row per account, tied to the account's printed summary.
import { useState } from "react";
import { useApi } from "../api.js";
import { Counts, ErrorBox, HumanBadge, Loading, MachineBadge } from "../components/common.jsx";
import { ActionBar, useCan } from "../components/Act.jsx";
import { SignOffForm, VerifyForm } from "../components/Forms.jsx";
import { change, figure, money, pct } from "../format.js";
import { href } from "../router.js";
import { Tick } from "../App.jsx";

const FILTERS = {
  all: { label: "All lines", test: () => true },
  flagged: { label: "With findings", test: (r) => r.findings.length > 0 },
  variance: { label: "Swings vs 2024", test: (r) => r.variance },
  adjusted: { label: "Adjusted", test: (r) => r.human_state?.state === "adjusted" },
};

export default function Area({ id, me, names, refreshKey }) {
  const { data, error } = useApi(`/api/areas/${id}`, refreshKey);
  const defaultFilter = me.config.default_filters?.includes("variance") ? "flagged" : "all";
  const [filter, setFilter] = useState(defaultFilter);
  const [picked, setPicked] = useState(new Set());
  const can = useCan();
  if (error) return <ErrorBox error={error} />;
  if (!data) return <Loading />;
  const { area, lines, accounts } = data;
  const shown = lines.filter(FILTERS[filter].test);
  const tip = data.meta.tip;
  const level = { preparer: "preparer", reviewer: "reviewer" }[me.person.role];
  const toggle = (key) => setPicked((s) => {
    const next = new Set(s);
    next.has(key) ? next.delete(key) : next.add(key);
    return next;
  });

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="crumbs">
            <a href={href.home()}>The return</a> ›
          </div>
          <h1>{area.label}</h1>
          {area.lens && <p className="muted">California lens: a signature over the California figures. It owns no documents.</p>}
        </div>
        <div className="signers">
          <SignerLine label="Preparer" status={area.preparer} names={names} />
          <SignerLine label="Reviewer" status={area.reviewer} names={names} />
          <a className="small" href={href.findings(area.id)}>
            Open findings <Counts counts={area.open_findings} />
          </a>
        </div>
      </div>

      {area.preparer.status === "reopened" && <Reopened status={area.preparer} />}
      {area.reviewer.status === "reopened" && <Reopened status={area.reviewer} />}

      <ActionBar
        actions={[
          { key: "sign", label: `Sign ${area.label} as ${level}`, primary: true, allowed: Boolean(level) && can("sign_off"),
            render: (done) => <SignOffForm area={area.id} label={area.label} tip={tip} level={level}
                                           openErrors={area.open_findings.error} onDone={done} /> },
          { key: "verify", label: `Verify ${picked.size} selected line${picked.size === 1 ? "" : "s"}`,
            allowed: picked.size > 0 && can("verify"),
            render: (done) => <VerifyForm targets={[...picked].map((k) => `line:${k}`)} tip={tip}
                                          what="One act; one undo reverses all of them."
                                          onDone={() => { setPicked(new Set()); done(); }} /> },
        ]}
      />

      <div className="filters">
        {Object.entries(FILTERS).map(([key, f]) => (
          <button key={key} className={filter === key ? "on" : ""} onClick={() => setFilter(key)}>
            {f.label} <span className="muted">{lines.filter(f.test).length}</span>
          </button>
        ))}
      </div>

      <LineTable rows={shown} names={names} picked={can("verify") ? picked : null} onPick={toggle} />

      {accounts.length > 0 && (
        <section>
          <h2>Sales by account</h2>
          <p className="muted small">One row per brokerage account. Lots open underneath.</p>
          {accounts.map((a) => (
            <Account key={a.document} account={a} names={names} />
          ))}
        </section>
      )}
    </div>
  );
}

function SignerLine({ label, status, names }) {
  return (
    <div className="signer-line">
      <Tick status={status.status} />
      <span>
        {label}: {status.by ? names[status.by] || status.by : <span className="muted">not signed</span>}
        {status.status === "reopened" && <span className="tag warn">reopened</span>}
        {status.waiver && (
          <span className="tag" title={`Waiver: ${status.waiver}`}>
            with waiver ({status.waived.length} open)
          </span>
        )}
      </span>
    </div>
  );
}

function Reopened({ status }) {
  return (
    <div className="callout warn">
      <strong>Signed on {status.signed_version}, reopened on {status.current_version}.</strong> Covered values changed:{" "}
      {Object.entries(status.causes || {}).map(([cause, keys]) => (
        <span key={cause} className="cause">
          {cause} ({keys.length})
        </span>
      ))}
    </div>
  );
}

export function LineTable({ rows, names, compact, picked, onPick }) {
  if (!rows.length) return <p className="muted">No lines match.</p>;
  return (
    <table className={`lines ${compact ? "compact" : ""}`}>
      <thead>
        <tr>
          {picked && <th className="pick" />}
          <th>Line</th>
          <th>Description</th>
          <th className="num">2024</th>
          <th className="num">2025</th>
          <th className="num">Change</th>
          <th>State</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <LineRow key={r.key} row={r} names={names} picked={picked} onPick={onPick} />
        ))}
      </tbody>
    </table>
  );
}

function LineRow({ row, names, picked, onPick }) {
  const c = change(row.value, row.prior);
  const go = () => (window.location.hash = href.line(row.key));
  return (
    <tr className="clickable" onClick={go}>
      {picked && (
        <td className="pick" onClick={(e) => e.stopPropagation()}>
          <input type="checkbox" checked={picked.has(row.key)} onChange={() => onPick(row.key)} aria-label={`Select ${row.key}`} />
        </td>
      )}
      <td className="key">
        <a href={href.line(row.key)} onClick={(e) => e.stopPropagation()}>
          {row.key}
        </a>
      </td>
      <td>{row.label}</td>
      <td className="num muted">{figure(row.prior, row.key)}</td>
      <td className="num">
        {figure(row.value, row.key)}
        {row.human_state?.state === "adjusted" && (
          <div className="engine small muted">
            {row.added_by ? "added: not on the engine's return" : `engine ${figure(row.engine_value, row.key)}`}
          </div>
        )}
      </td>
      <td className={`num ${row.variance ? "flag" : "muted"}`}>{c ? `${money(c.diff)} ${pct(c.pct)}` : ""}</td>
      <td className="states">
        <MachineBadge state={row.machine_state} />
        <HumanBadge human={row.human_state} names={names} />
        {row.findings.length > 0 && <span className="muted small">{row.findings.length} finding{row.findings.length > 1 ? "s" : ""}</span>}
      </td>
    </tr>
  );
}

function Account({ account, names }) {
  const [open, setOpen] = useState(false);
  const tone = { ties: "ties", gap: "bad", "no printed summary": "muted" }[account.summary];
  return (
    <div className="account">
      <button className="account-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="chev">{open ? "▾" : "▸"}</span>
        <span className="account-title">
          <a href={href.doc(account.document)} onClick={(e) => e.stopPropagation()}>
            {account.document}
          </a>{" "}
          {account.title}
        </span>
        <span className="muted small">{account.lots} lots</span>
        <span className="num">{money(account.gain, { cents: true })}</span>
        <span className={`badge machine tone-${tone}`}>
          {account.summary === "ties" ? "Lots tie to printed summary" : account.summary === "gap" ? "Lots do not add to summary" : "No printed summary"}
        </span>
        {account.open_findings.length > 0 && <span className="muted small">{account.open_findings.length} findings</span>}
      </button>
      {account.reconciliation && (
        <div className="small muted account-tie">
          Printed summary proceeds {money(account.reconciliation.summary_proceeds, { cents: true })} = sum of{" "}
          {account.reconciliation.lots} lots {money(account.reconciliation.lot_proceeds, { cents: true })}
          {account.reconciliation.added_lots > 0 && ` (${account.reconciliation.added_lots} added by a person from a page the pipeline never read)`}.
        </div>
      )}
      {open && <LineTable rows={account.lot_rows} names={names} compact />}
    </div>
  );
}
