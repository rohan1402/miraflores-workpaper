// Home (D1): the return, 2025 vs 2024, by work area. Role changes the order and focus, not the home.
import { useApi } from "../api.js";
import { useState } from "react";
import { Counts, ErrorBox, Estimate, Loading, Ref } from "../components/common.jsx";
import { useCan } from "../components/Act.jsx";
import { ReleaseForm, ResolveForm } from "../components/Forms.jsx";
import { ROLE_LABEL, change, date, dateTime, money, pct } from "../format.js";
import { href } from "../router.js";
import { Tick } from "../App.jsx";

export default function Home({ me, names, refreshKey }) {
  const { data, error } = useApi("/api/return", refreshKey);
  if (error) return <ErrorBox error={error} />;
  if (!data) return <Loading />;
  const { meta, strip, areas, release_blockers: blockers, partner_release: release, open_corrections: open } = data;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>The return</h1>
          <p className="muted">
            2025 against 2024 · current version <strong>{meta.version}</strong>, computed {date(meta.computed_at)}
            <span className="trigger" title={meta.trigger}> · why recomputed</span>
          </p>
        </div>
        <div className="focus">
          <span className="muted">{ROLE_LABEL[me.person.role]} view</span>
          <strong>{me.config.focus}</strong>
        </div>
      </div>

      {data.filing.frozen && (
        <div className="callout">
          <strong>Filed.</strong> The return is frozen; <a href={href.filing()}>open an amendment</a> to change it.
        </div>
      )}
      {data.filing.amendment_open && (
        <div className="callout warn">
          <strong>Amendment open.</strong> Changes now build the amended return. <a href={href.filing()}>Filing</a>
        </div>
      )}

      <Strip rows={strip} />

      <div className="home-grid">
        <section>
          <h2>Work areas</h2>
          <div className="area-cards">
            {areas.map((a) => (
              <AreaCard key={a.id} area={a} names={names} />
            ))}
          </div>
        </section>
        <aside className="side">
          <ReleaseCard release={release} blockers={blockers} names={names} areas={areas}
                       preview={data.release_will_approve} tip={meta.tip} />
          <ReviewNotes notes={data.review_notes} names={names} tip={meta.tip} />
          <div className="card">
            <h3>If every open correction were made</h3>
            <p className="muted small">
              Change in tax from the checker's proposed corrections, each line built once. Not a recomputed return. <Estimate />
            </p>
            <div className="effect-pair">
              <EffectFigure label="Federal tax" value={open.federal} />
              <EffectFigure label="California tax" value={open.california} />
            </div>
            <a href={href.findings()} className="small">
              {open.findings.length} findings carry a dollar effect →
            </a>
          </div>
        </aside>
      </div>
    </div>
  );
}

function Strip({ rows }) {
  const groups = [
    ["Federal", rows.filter((r) => r.jurisdiction === "federal")],
    ["California", rows.filter((r) => r.jurisdiction === "california")],
  ];
  return (
    <div className="strip">
      {groups.map(([title, cells]) => (
        <div key={title} className="strip-row">
          <div className="strip-title">{title}</div>
          {cells.map((r) => (
            <StripCell key={r.name} row={r} />
          ))}
        </div>
      ))}
    </div>
  );
}

function StripCell({ row }) {
  const c = change(row.value, row.prior);
  const short = row.label.replace(" (refund negative)", "").replace("California ", "");
  const label = short.charAt(0).toUpperCase() + short.slice(1);
  // A percentage across a sign flip (refund to amount owed) means nothing: show dollars instead.
  const flipped = c && Math.sign(row.value) !== Math.sign(row.prior);
  return (
    <a className={`strip-cell ${row.variance ? "flagged" : ""}`} href={href.line(row.line)} title={`Trace ${row.line}`}>
      <span className="strip-label">{label}</span>
      <span className="strip-value num">{money(row.value)}</span>
      <span className="strip-prior">
        2024 <span className="num">{money(row.prior)}</span>
        {c && <span className={`delta ${row.variance ? "flag" : ""}`}>{flipped ? `${c.diff > 0 ? "+" : ""}${money(c.diff)}` : pct(c.pct)}</span>}
      </span>
      {row.estimated && (
        <span className="strip-estimate" title="Balance due if every open checker correction were made (estimate)">
          after corrections <span className="num">{money(row.estimated.after_open_corrections)}</span>
        </span>
      )}
    </a>
  );
}

function AreaCard({ area, names }) {
  return (
    <a className={`area-card ${area.lens ? "lens" : ""} ${area.complete ? "complete" : ""}`} href={href.area(area.id)}>
      <div className="area-card-head">
        <strong>{area.label}</strong>
        <Counts counts={area.open_findings} />
      </div>
      {area.lens && <div className="lens-note">Signs a view across the areas; owns no documents.</div>}
      <div className="area-card-foot">
        <Signer label="Preparer" status={area.preparer} names={names} />
        <Signer label="Reviewer" status={area.reviewer} names={names} />
        <span className="muted small">
          {area.lines} lines{area.budget_hours ? ` · ${area.budget_hours} h budget` : ""}
        </span>
      </div>
    </a>
  );
}

function Signer({ label, status, names }) {
  return (
    <span className="signer">
      <Tick status={status.status} />
      <span className="small">
        {label}
        {status.by ? `: ${names[status.by] || status.by}` : ""}
      </span>
    </span>
  );
}

function ReleaseCard({ release, blockers, names, areas, preview, tip }) {
  const label = (id) => areas.find((a) => a.id === id)?.label || id;
  const can = useCan();
  const [releasing, setReleasing] = useState(false);
  return (
    <div className={`card release ${release.status}`}>
      <h3>Partner release</h3>
      {release.status === "unsigned" && <p className="small muted">Not released.</p>}
      {release.status === "signed" && <p className="small">Released by {names[release.by] || release.by}.</p>}
      {release.status === "reopened" && <p className="small">Released, then reopened: something it signed changed.</p>}
      {blockers.length ? (
        <>
          <div className="small strong">Blocked by</div>
          <ul className="blockers">
            {blockers.map((b) => {
              const area = b.match(/^area not signed: (.+)$/);
              return <li key={b}>{area ? <a href={href.area(area[1])}>{label(area[1])} not signed</a> : b}</li>;
            })}
          </ul>
        </>
      ) : (
        <p className="small ok">Nothing blocks the release.</p>
      )}
      {can("partner_release") && !blockers.length && release.status !== "signed" && (
        releasing ? (
          <ReleaseForm tip={tip} preview={preview} onDone={() => setReleasing(false)} />
        ) : (
          <button className="primary" onClick={() => setReleasing(true)}>
            Release the return
          </button>
        )
      )}
    </div>
  );
}

// Open review notes block the release until someone resolves them.
function ReviewNotes({ notes, names, tip }) {
  const can = useCan();
  const [resolving, setResolving] = useState(null);
  if (!notes.length) return null;
  return (
    <div className="card">
      <h3>Open review notes</h3>
      <ul className="notes-list">
        {notes.map((n) => (
          <li key={n.event}>
            <div className="small muted">
              {names[n.by] || n.by} · {dateTime(n.at)} · on {n.targets.map((t) => <Ref key={t} value={t} />)}
            </div>
            <div>{n.text}</div>
            {can("resolve_review_note") && resolving !== n.event && (
              <button className="link small" onClick={() => setResolving(n.event)}>
                Resolve
              </button>
            )}
            {resolving === n.event && <ResolveForm noteEvent={n.event} tip={tip} onDone={() => setResolving(null)} />}
          </li>
        ))}
      </ul>
    </div>
  );
}

function EffectFigure({ label, value }) {
  return (
    <div className="effect-figure">
      <span className="muted small">{label}</span>
      <span className={`num estimate-figure ${value < 0 ? "down" : value > 0 ? "up" : ""}`}>
        {value > 0 ? "+" : ""}
        {money(value)}
      </span>
    </div>
  );
}
