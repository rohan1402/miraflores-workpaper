// Trace one number both ways: down to the exact field on a page, and up to every line it feeds.
import { useApi } from "../api.js";
import { ErrorBox, Estimate, HumanBadge, Loading, MachineBadge } from "../components/common.jsx";
import FindingCard from "../components/FindingCard.jsx";
import { LineTable } from "./Area.jsx";
import { date, dateTime, figure, money, VERIFICATION_LABEL } from "../format.js";
import { href } from "../router.js";

export default function Line({ lineKey, names, refreshKey }) {
  const { data, error } = useApi(`/api/lines/${encodeURIComponent(lineKey)}`, refreshKey);
  const areas = useApi("/api/return", refreshKey).data?.areas || [];
  if (error) return <ErrorBox error={error} />;
  if (!data) return <Loading />;
  const { line, rule, note, inputs, used_by: usedBy, sources, versions, adjustments, verifications, findings, scopes } = data;
  const label = (id) => areas.find((a) => a.id === id)?.label || id;

  return (
    <div className="page">
      <div className="crumbs">
        <a href={href.home()}>The return</a> ›{" "}
        {scopes
          .filter((s) => s !== "return")
          .map((s) => (
            <a key={s} href={href.area(s)} className="crumb-area">
              {label(s)}
            </a>
          ))}
        {scopes.includes("return") && <span className="muted">bottom line (partner)</span>}
      </div>

      <div className="line-head">
        <div>
          <code className="key big">{line.key}</code>
          <h1>{line.label}</h1>
          <div className="states">
            <MachineBadge state={line.machine_state} />
            <HumanBadge human={line.human_state} names={names} />
          </div>
        </div>
        <div className="line-figures">
          <div>
            <span className="muted small">2025</span>
            <span className="num huge">{figure(line.value, line.key)}</span>
            {line.human_state?.state === "adjusted" && (
              <span className="small muted">engine {figure(line.engine_value, line.key)}</span>
            )}
          </div>
          <div>
            <span className="muted small">2024{line.prior_line && line.prior_line !== line.key ? ` (${line.prior_line})` : ""}</span>
            <span className="num">{figure(line.prior, line.key) || "—"}</span>
          </div>
          <div className="versions" title="Engine value at each computed version">
            {Object.entries(versions).map(([v, value]) => (
              <span key={v}>
                <span className="muted small">{v}</span> <span className="num">{value === null ? "none" : figure(value, line.key)}</span>
              </span>
            ))}
          </div>
        </div>
      </div>

      {findings.length > 0 && (
        <section>
          <h2>What the checker found</h2>
          {findings.map((f) => (
            <FindingCard key={f.id} finding={f} names={names} />
          ))}
        </section>
      )}

      <section>
        <h2>How it was built</h2>
        <p>
          <code className="code">{rule.id}</code> {rule.description}
        </p>
        {note && <p className="note">Engine note: {note}</p>}
        {inputs.length > 0 && <LineTable rows={inputs} names={names} compact />}
      </section>

      {sources.length > 0 && (
        <section>
          <h2>Where it came from</h2>
          <div className="sources">
            {sources.map((s) => (
              <Source key={s.ref} source={s} names={names} />
            ))}
          </div>
        </section>
      )}

      <section>
        <h2>Where it goes</h2>
        {usedBy.length ? (
          <div className="chips">
            {usedBy.map((k) => (
              <a key={k} className="chip key" href={href.line(k)}>
                {k}
              </a>
            ))}
          </div>
        ) : (
          <p className="muted">No other line uses it.</p>
        )}
      </section>

      {adjustments.length > 0 && (
        <section>
          <h2>Adjustments</h2>
          <table className="lines compact">
            <thead>
              <tr>
                <th>When</th>
                <th>Who</th>
                <th className="num">From</th>
                <th className="num">To</th>
                <th>Why</th>
                <th>Tax effect</th>
              </tr>
            </thead>
            <tbody>
              {adjustments.map((a) => (
                <tr key={a.event} className={a.applied ? "" : "stale"}>
                  <td>{dateTime(a.at)}</td>
                  <td>{names[a.by] || a.by}</td>
                  <td className="num">{figure(a.from, line.key)}</td>
                  <td className="num">{figure(a.to, line.key)}</td>
                  <td>
                    {a.reason}
                    {!a.applied && <span className="tag warn">stale: the figure changed since</span>}
                  </td>
                  <td className="small">
                    {a.effect.stored && (
                      <>
                        fed {money(a.effect.stored.federal)}, CA {money(a.effect.stored.california)} <Estimate />
                      </>
                    )}
                    {a.effect.differs && (
                      <div className="muted">
                        at today's rates: fed {money(a.effect.fresh.federal)}, CA {money(a.effect.fresh.california)}
                      </div>
                    )}
                    {a.needs_partner && (
                      <div className={a.partner_approved ? "ok" : "warn"}>
                        {a.partner_approved ? "partner approved" : "over $1,000: partner signs it"}
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {verifications.length > 0 && (
        <section>
          <h2>Verified by people</h2>
          <ul className="plain">
            {verifications.map((v) => (
              <li key={v.event}>
                {names[v.by] || v.by}, {VERIFICATION_LABEL[v.type] || v.type}, {date(v.at)}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function Source({ source: s, names }) {
  if (s.kind === "document_value") {
    return (
      <a className="source doc" href={href.doc(s.document, s.page, s.ref)}>
        <span className="source-where">
          <strong>{s.document}</strong> page {s.page} · <code>{s.field}</code>
        </span>
        <span className="source-what">
          {s.label}: <span className="num">{s.value === null ? "nothing read" : String(s.value)}</span>
          {s.text_as_read && String(s.text_as_read) !== String(s.value) && (
            <span className="muted"> (read as “{s.text_as_read}”)</span>
          )}
        </span>
        <span className="source-meta">
          <MachineBadge state={s.machine_state} />
          <span className={`conf ${s.confidence < 0.8 ? "low" : ""}`}>read at {s.confidence}</span>
          {s.verified.length > 0 && <span className="badge human verified">Verified · {s.verified.length}</span>}
        </span>
        <span className="source-title muted small">{s.title}</span>
      </a>
    );
  }
  if (s.kind.startsWith("client_")) {
    // Client answers are a distinct kind of evidence (D2): a memory, not a form.
    return (
      <div className="source client">
        <span className="source-where">
          <strong>Client said</strong> · {s.ref} · {date(s.at)}
          {s.from ? ` · ${s.from}` : ""}
        </span>
        {s.question && <span className="muted small">Q: {s.question}</span>}
        <blockquote>{s.text}</blockquote>
      </div>
    );
  }
  return (
    <div className="source ref-source">
      <span className="source-where">
        <strong>{s.kind.replace(/_/g, " ")}</strong> · <code>{s.ref}</code>
      </span>
      <span className="muted small">{summarize(s.value)}</span>
    </div>
  );
}

function summarize(value) {
  if (value === null || value === undefined) return "";
  if (typeof value !== "object") return String(value);
  const text = JSON.stringify(value);
  return text.length > 220 ? `${text.slice(0, 220)}…` : text;
}
