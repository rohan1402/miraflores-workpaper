// A simulated source document. Each page is its printed text (the truth) plus the values the
// pipeline read from it. On a simulated page the exact location is marked in the text itself.
// The packet's `position` boxes are synthetic and do not line up with the text, so they are drawn
// only over a real page image (page.image); when images arrive, nothing else changes.
import { useEffect, useRef, useState } from "react";
import { postJSON, useApi } from "../api.js";
import { ErrorBox, HumanBadge, Loading, MachineBadge } from "../components/common.jsx";
import FindingCard from "../components/FindingCard.jsx";
import History from "../components/History.jsx";
import { ActionBar, useCan } from "../components/Act.jsx";
import { AcceptForm, AttachForm, DispositionForm, NoteForm, QuestionForm, VerifyForm } from "../components/Forms.jsx";
import PageText, { printedValue, valueNeedles } from "../components/PageText.jsx";
import { date } from "../format.js";
import { href } from "../router.js";

const SENSITIVE = new Set(["ssn", "account_number"]);

export default function Document({ docId, params, me, names, refreshKey }) {
  const { data, error } = useApi(`/api/documents/${docId}`, refreshKey);
  const [selected, setSelected] = useState(params.ev || null);
  const [pageNo, setPageNo] = useState(Number(params.page) || null);

  useEffect(() => {
    setSelected(params.ev || null);
    setPageNo(Number(params.page) || null);
  }, [docId, params.ev, params.page]);

  if (error) return <ErrorBox error={error} />;
  if (!data) return <Loading />;
  const { document: d, pages, landed_on: landed, not_used_because: notUsed, disposition, owners, findings } = data;
  const tip = data.meta.tip;
  const current = pages.find((p) => p.page === pageNo) || pages.find((p) => p.values.some((v) => v.id === selected)) || pages[0];

  const choose = (page, ev) => {
    setPageNo(page);
    setSelected(ev);
    // Keep the address shareable without a route change (which would scroll to the top).
    window.history.replaceState(null, "", href.doc(docId, page, ev));
  };

  return (
    <div className="page">
      <div className="crumbs">
        <a href={href.documents()}>Documents</a> ›
      </div>
      <div className="doc-head">
        <div>
          <h1>
            <span className="key">{d.id}</span> {d.title}
          </h1>
          <p className="muted">
            {d.document_type} · {d.issuer} · received {date(d.received_at)} · {d.page_count} page{d.page_count > 1 ? "s" : ""}
            {d.marked_corrected && <span className="tag warn">CORRECTED</span>}
          </p>
        </div>
        <dl className="doc-facts">
          <dt>Extraction</dt>
          <dd className={d.extraction.status !== "extracted" ? "warn" : ""}>
            {d.extraction.status}
            {d.extraction.reason && <span className="muted small"> · {d.extraction.reason}</span>}
          </dd>
          <dt>Disposition</dt>
          <dd>{disposition ? `${disposition.value} (${names[disposition.by] || disposition.by})` : <span className="muted">not yet</span>}</dd>
          <dt>Owned by</dt>
          <dd>{owners.length ? owners.map((o) => o.replace(/_/g, " ")).join(", ") : <span className="muted">no area</span>}</dd>
          <dt>Landed on</dt>
          <dd>
            {landed.length ? (
              <span className="chips">
                {landed.map((k) => (
                  <a key={k} className="chip key" href={href.line(k)}>
                    {k}
                  </a>
                ))}
              </span>
            ) : (
              // A dispositioned document landing nowhere is settled; one without a disposition is a question.
              <span className={disposition ? "muted" : "warn"}>nowhere: {notUsed}</span>
            )}
          </dd>
        </dl>
      </div>

      <DocumentActions doc={d} tip={tip} findings={findings} reconciliation={data.reconciliation} />

      {findings.length > 0 && (
        <details className="doc-findings" open={findings.some((f) => f.severity === "error")}>
          <summary>
            {findings.length} checker finding{findings.length > 1 ? "s" : ""} on this document
          </summary>
          {findings.map((f) => (
            <FindingCard key={f.id} finding={f} tip={tip} />
          ))}
        </details>
      )}

      {pages.length > 1 && (
        <div className="page-tabs">
          {pages.map((p) => (
            <button
              key={p.page}
              className={`${p.page === current.page ? "on" : ""} ${p.read ? "" : "unread"}`}
              onClick={() => choose(p.page, null)}
              title={p.read ? `${p.values.length} values read` : "Not read by the pipeline"}
            >
              {p.page}
            </button>
          ))}
        </div>
      )}

      <PageView key={`${d.id}-${current.page}`} page={current} selected={selected} onSelect={(ev) => choose(current.page, ev)}
                me={me} names={names} tip={tip} />

      <History refId={d.id} tip={tip} refreshKey={refreshKey} />
    </div>
  );
}

// What the checker found suggests the disposition; a person still records it, with a reason.
function suggestedDisposition(doc, findings) {
  for (const f of findings) {
    if (f.code === "DUPLICATE_DOCUMENT" && f.targets.includes(doc.id)) return { disposition: "duplicate", of: f.details.duplicate_of };
    if (f.code === "SUPERSEDED_DOCUMENT" && f.details.superseded === doc.id) return { disposition: "superseded", by: f.details.by };
    if (f.code === "DOCUMENT_NOT_EXTRACTED") return { disposition: "not_extracted" };
  }
  const unread = findings.filter((f) => f.code === "PAGE_NOT_READ").map((f) => Number(f.id.split("#page")[1]));
  if (unread.length) return { disposition: "partial", pages: unread };
  return { disposition: "used" };
}

function DocumentActions({ doc, tip, findings, reconciliation }) {
  const can = useCan();
  const count = doc.extraction.values;
  return (
    <ActionBar
      actions={[
        { key: "disposition", label: "Disposition", primary: true, allowed: can("disposition"),
          render: (done) => <DispositionForm doc={doc.id} tip={tip} pages={doc.page_count}
                                             suggestion={suggestedDisposition(doc, findings)} onDone={done} /> },
        { key: "accept", label: `Accept all ${count} values`, allowed: can("accept_document") && count > 0,
          render: (done) => <AcceptForm doc={doc.id} tip={tip} count={count} ties={Boolean(reconciliation)} onDone={done} /> },
        { key: "note", label: "Note", allowed: can("note"),
          render: (done) => <NoteForm targets={[doc.id]} tip={tip} onDone={done} /> },
        { key: "ask", label: "Ask", allowed: can("question"),
          render: (done) => <QuestionForm targets={[doc.id]} tip={tip} onDone={done} /> },
        { key: "attach", label: "Attach evidence", allowed: can("attach_evidence"),
          render: (done) => <AttachForm targets={[doc.id]} tip={tip} onDone={done} /> },
      ]}
    />
  );
}

function PageView({ page, selected, onSelect, me, names, tip }) {
  const [showAll, setShowAll] = useState(false);
  const [revealed, setRevealed] = useState({});
  const [verifying, setVerifying] = useState(null);
  const can = useCan();
  const chosen = page.values.find((v) => v.id === selected);
  const selectedRow = useRef(null);

  useEffect(() => {
    selectedRow.current?.scrollIntoView({ block: "nearest" });
  }, [selected]);

  const unmask = async (ev) => {
    const r = await postJSON("/api/unmask", { ref: ev.id });
    setRevealed((x) => ({ ...x, [ev.id]: r.value }));
  };

  return (
    <div className="page-view">
      <div className="paper-col">
        {!page.read && (
          <div className="callout bad">The pipeline did not read this page. Anything printed here is not on the return yet.</div>
        )}
        <div className="paper">
          {page.image && <img src={page.image} alt={`Page ${page.page}`} className="paper-image" />}
          {!page.image && (
            <PageText
              className="paper-text"
              text={page.text}
              marks={[
                ...(chosen ? [{ needles: valueNeedles(chosen), kind: "selected", title: chosen.label }] : []),
                ...page.quotes.map((q) => ({ needles: [q.text], kind: "quote", title: `Relied on by: ${q.title}` })),
              ]}
            />
          )}
          {page.image && (
          <div className="boxes">
            {page.values.map((v) =>
              showAll || v.id === selected ? (
                <button
                  key={v.id}
                  className={`box ${v.id === selected ? "selected" : ""} tone-${v.machine_state}`}
                  style={boxStyle(v.position)}
                  onClick={() => onSelect(v.id)}
                  title={`${v.label}: ${v.text_as_read || v.value}`}
                >
                  {v.id === selected && <span className="box-tag">{v.field}</span>}
                </button>
              ) : null,
            )}
          </div>
          )}
        </div>
        {page.image ? (
          <label className="small muted toggle">
            <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} /> Show every field the pipeline read
          </label>
        ) : (
          <p className="small muted toggle">
            Simulated page from the packet's printed text. The selected value is marked where it is printed.
          </p>
        )}
      </div>

      <div className="values-col">
        <h3>
          Read from page {page.page} <span className="muted small">{page.values.length} values</span>
        </h3>
        {page.values.length === 0 && <p className="muted small">No values read from this page.</p>}
        <div className="values">
          {page.values.map((v) => (
            <div
              key={v.id}
              ref={v.id === selected ? selectedRow : null}
              className={`value-row ${v.id === selected ? "selected" : ""}`}
              onClick={() => onSelect(v.id)}
            >
              <div className="value-main">
                <code className="field">{v.field}</code>
                <span className="value-label">{v.label}</span>
                <span className="num value">{revealed[v.id] ?? printedValue(v)}</span>
              </div>
              <div className="value-meta">
                <MachineBadge state={v.machine_state} />
                <span className={`conf ${v.confidence < 0.8 ? "low" : ""}`}>read at {v.confidence}</span>
                {v.verified.length > 0 && <HumanBadge human={{ state: "verified", ...lastVerified(v.verified) }} names={names} />}
                {SENSITIVE.has(v.value_type) && me.clearance && !revealed[v.id] && (
                  <button className="link small" onClick={(e) => (e.stopPropagation(), unmask(v))} title="Shows the full value. The view is logged.">
                    unmask (logged)
                  </button>
                )}
                {v.lines.map((k) => (
                  <a key={k} className="chip key" href={href.line(k)} onClick={(e) => e.stopPropagation()}>
                    {k}
                  </a>
                ))}
                {v.lines.length === 0 && <span className="muted small">on no line</span>}
                {can("verify") && verifying !== v.id && (
                  <button className="link small" onClick={(e) => (e.stopPropagation(), setVerifying(v.id))}>
                    verify
                  </button>
                )}
              </div>
              {verifying === v.id && (
                <div className="value-verify" onClick={(e) => e.stopPropagation()}>
                  <VerifyForm targets={[v.id]} tip={tip} what={`${v.label} as printed on page ${page.page}`} onDone={() => setVerifying(null)} />
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function lastVerified(list) {
  const v = list[list.length - 1];
  return { by: v.by, at: v.at, type: v.type };
}

function boxStyle(p) {
  return {
    left: `${p.x0 * 100}%`,
    top: `${p.y0 * 100}%`,
    width: `${(p.x1 - p.x0) * 100}%`,
    height: `${(p.y1 - p.y0) * 100}%`,
  };
}

