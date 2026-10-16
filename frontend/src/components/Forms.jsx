// The workflow forms. Each collects only what the person chooses and posts it as one act.
// Derived values (an adjustment's "from" and tax effect, a sign-off's fingerprint) come from the server.
import { useEffect, useState } from "react";
import { getJSON, useApp } from "../api.js";
import { ActError, Field, VERIFICATION_TYPES, useAct } from "./Act.jsx";
import { Estimate } from "./common.jsx";
import { figure, money } from "../format.js";

function Submit({ busy, disabled, children, onCancel }) {
  return (
    <div className="form-buttons">
      <button className="primary" disabled={busy || disabled} type="submit">
        {busy ? "Saving…" : children}
      </button>
      {onCancel && (
        <button type="button" className="link" onClick={onCancel}>
          Cancel
        </button>
      )}
    </div>
  );
}

function TypeSelect({ value, onChange }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)}>
      {VERIFICATION_TYPES.map(([id, label]) => (
        <option key={id} value={id}>
          {label}
        </option>
      ))}
    </select>
  );
}

// Only a person verifies (D2): one of the firm's five verification types, never "high confidence".
export function VerifyForm({ targets, tip, what, onDone }) {
  const { run, busy, error } = useAct();
  const [type, setType] = useState("agreed_to_source_document");
  const submit = async (e) => {
    e.preventDefault();
    if (await run({ action: "verify", targets, payload: { verification_type: type }, tip })) onDone?.();
  };
  return (
    <form onSubmit={submit}>
      <Field label="How you verified" hint={what}>
        <TypeSelect value={type} onChange={setType} />
      </Field>
      <ActError error={error} />
      <Submit busy={busy} onCancel={onDone}>
        Verify{targets.length > 1 ? ` ${targets.length} items` : ""}
      </Submit>
    </form>
  );
}

// Change a figure without losing the original. The estimate is previewed by the server before saving.
export function AdjustForm({ line, current, tip, finding, suggested, adds, onDone }) {
  const { run, busy, error } = useAct();
  const [to, setTo] = useState(suggested ?? "");
  const [reason, setReason] = useState("");
  const [preview, setPreview] = useState(null);

  useEffect(() => {
    const value = Number(to);
    if (to === "" || Number.isNaN(value)) return setPreview(null);
    const timer = setTimeout(() => {
      getJSON(`/api/estimate?line=${encodeURIComponent(line)}&to=${value}`).then(setPreview).catch(() => setPreview(null));
    }, 250);
    return () => clearTimeout(timer);
  }, [line, to]);

  const submit = async (e) => {
    e.preventDefault();
    const payload = { to: Number(to), ...(finding ? { finding } : {}) };
    if (await run({ action: "adjust", targets: [`line:${line}`], payload, reason, tip })) onDone?.();
  };
  return (
    <form onSubmit={submit}>
      <Field label={adds ? `Figure for the new line ${line}` : `New figure for ${line}`}
             hint={adds ? `Not on the return yet. This adds it: ${adds}.` : `Now ${figure(current, line)}. The original stays on record.`}>
        <input type="number" step="any" value={to} onChange={(e) => setTo(e.target.value)} autoFocus />
      </Field>
      <Field label="Why">
        <textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="The reason goes on the record" />
      </Field>
      {finding && <div className="small muted">Answers finding {finding}.</div>}
      {preview?.effect && (
        <div className="preview small">
          Tax effect: federal {signed(preview.effect.federal)}, California {signed(preview.effect.california)} <Estimate />
          {preview.needs_partner && <span className="tag warn">over $1,000: the partner signs it</span>}
        </div>
      )}
      <ActError error={error} />
      <Submit busy={busy} disabled={to === "" || !reason.trim()} onCancel={onDone}>
        Save adjustment
      </Submit>
    </form>
  );
}

// A note always appends. A review note stays open until resolved and blocks the partner release.
export function NoteForm({ targets, tip, review, onDone }) {
  const { run, busy, error } = useAct();
  const [text, setText] = useState("");
  const submit = async (e) => {
    e.preventDefault();
    if (await run({ action: review ? "review_note" : "note", targets, payload: { text }, tip })) onDone?.();
  };
  return (
    <form onSubmit={submit}>
      <Field label={review ? "Review note" : "Note"} hint={review ? "Open until resolved. Open review notes block the release." : null}>
        <textarea rows={3} value={text} onChange={(e) => setText(e.target.value)} autoFocus />
      </Field>
      <ActError error={error} />
      <Submit busy={busy} disabled={!text.trim()} onCancel={onDone}>
        {review ? "Open review note" : "Add note"}
      </Submit>
    </form>
  );
}

export function ResolveForm({ noteEvent, tip, onDone }) {
  const { run, busy, error } = useAct();
  const [text, setText] = useState("");
  const submit = async (e) => {
    e.preventDefault();
    if (await run({ action: "resolve_review_note", targets: [`event:${noteEvent}`], payload: { text }, tip })) onDone?.();
  };
  return (
    <form onSubmit={submit} className="inline-form">
      <input value={text} onChange={(e) => setText(e.target.value)} placeholder="How it was resolved" />
      <ActError error={error} />
      <Submit busy={busy} disabled={!text.trim()} onCancel={onDone}>
        Resolve
      </Submit>
    </form>
  );
}

// A question to the client or a colleague. The answer becomes evidence.
export function QuestionForm({ targets, tip, onDone }) {
  const { names, me } = useApp();
  const { run, busy, error } = useAct();
  const [to, setTo] = useState("client");
  const [text, setText] = useState("");
  const staff = Object.entries(names).filter(([id]) => id.startsWith("st-") && id !== me.person.id);
  const submit = async (e) => {
    e.preventDefault();
    if (await run({ action: "question", targets, payload: { to, text }, tip })) onDone?.();
  };
  return (
    <form onSubmit={submit}>
      <Field label="To">
        <select value={to} onChange={(e) => setTo(e.target.value)}>
          <option value="client">The client (Ngozi and Erik)</option>
          {staff.map(([id, name]) => (
            <option key={id} value={id}>
              {name}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Question">
        <textarea rows={3} value={text} onChange={(e) => setText(e.target.value)} autoFocus />
      </Field>
      <ActError error={error} />
      <Submit busy={busy} disabled={!text.trim()} onCancel={onDone}>
        Send question
      </Submit>
    </form>
  );
}

// Accept a finding as it stands. Firm rule: every judgment call records the authority relied on.
export function JudgmentForm({ finding, effect, toPartner, tip, onDone }) {
  const { run, busy, error } = useAct();
  const [decision, setDecision] = useState("");
  const [authority, setAuthority] = useState("");
  const [reason, setReason] = useState("");
  const submit = async (e) => {
    e.preventDefault();
    if (await run({ action: "judgment_call", targets: [`finding:${finding}`], payload: { decision, authority }, reason, tip })) onDone?.();
  };
  return (
    <form onSubmit={submit}>
      <Field label="Decision">
        <input value={decision} onChange={(e) => setDecision(e.target.value)} placeholder="e.g. Keep zero basis" autoFocus />
      </Field>
      <Field label="Authority relied on" hint="Required by the firm: code section, regulation, ruling or firm policy.">
        <input value={authority} onChange={(e) => setAuthority(e.target.value)} placeholder="e.g. Treas. Reg. 1.6001-1(a)" />
      </Field>
      <Field label="Why">
        <textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
      </Field>
      {toPartner && (
        <p className="small">
          Accepting keeps a correction of federal {signed(effect.federal)}, California {signed(effect.california)} off
          the return. That is over the firm's $1,000 threshold, so the partner release will list it.
        </p>
      )}
      <ActError error={error} />
      <Submit busy={busy} disabled={!decision.trim() || !authority.trim()} onCancel={onDone}>
        Record judgment call
      </Submit>
    </form>
  );
}

const DISPOSITIONS = [
  ["used", "Used on the return"],
  ["duplicate", "Duplicate of another document"],
  ["superseded", "Superseded by a corrected document"],
  ["not_extracted", "Not extracted (content used elsewhere)"],
  ["partial", "Partial: some pages unread"],
];

// The disposition the open findings on a document point to, to prefill the form. Each rule says
// what answers its finding (finding.answer, D19 and D20); the person still chooses and gives the reason.
export function suggestedDisposition(docId, findings) {
  const answers = findings.filter((f) => f.status === "open" && f.answer?.act === "disposition" && f.answer.document === docId)
    .map((f) => f.answer);
  const whole = answers.find((a) => a.disposition !== "partial");
  if (whole) return whole;
  const pages = answers.flatMap((a) => a.pages || []);
  return pages.length ? { disposition: "partial", pages } : { disposition: "used" };
}

// Disposition comes first (D2): what this document is to the return, and why.
export function DispositionForm({ doc, tip, pages, suggestion = {}, onDone }) {
  const { run, busy, error } = useAct();
  const [value, setValue] = useState(suggestion.disposition || "used");
  const [other, setOther] = useState(suggestion.of || suggestion.by || "");
  const [chosenPages, setChosenPages] = useState((suggestion.pages || []).join(", "));
  const [reason, setReason] = useState("");
  const submit = async (e) => {
    e.preventDefault();
    const payload = { disposition: value };
    if (value === "duplicate") payload.of = other.trim();
    if (value === "superseded") payload.by = other.trim();
    if (value === "partial") payload.pages = chosenPages.split(/[ ,]+/).filter(Boolean).map(Number);
    if (await run({ action: "disposition", targets: [doc], payload, reason, tip })) onDone?.();
  };
  return (
    <form onSubmit={submit}>
      <Field label="Disposition">
        <select value={value} onChange={(e) => setValue(e.target.value)}>
          {DISPOSITIONS.map(([id, label]) => (
            <option key={id} value={id}>
              {label}
            </option>
          ))}
        </select>
      </Field>
      {(value === "duplicate" || value === "superseded") && (
        <Field label={value === "duplicate" ? "Copy of document" : "Replaced by document"}>
          <input value={other} onChange={(e) => setOther(e.target.value)} placeholder="e.g. D09" />
        </Field>
      )}
      {value === "partial" && (
        <Field label="Pages this covers" hint={pages ? `This document has ${pages} pages.` : undefined}>
          <input value={chosenPages} onChange={(e) => setChosenPages(e.target.value)} placeholder="e.g. 32" />
        </Field>
      )}
      <Field label="Why">
        <textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
      </Field>
      <ActError error={error} />
      <Submit busy={busy} disabled={!reason.trim()} onCancel={onDone}>
        Record disposition
      </Submit>
    </form>
  );
}

// Accept every value of a document in one act, page beside the values (D2). An account whose lots
// tie to its printed summary can be accepted at the summary.
export function AcceptForm({ doc, tip, count, ties, onDone }) {
  const { run, busy, error } = useAct();
  const [type, setType] = useState("agreed_to_source_document");
  const submit = async (e) => {
    e.preventDefault();
    const payload = { verification_type: type, at_summary: Boolean(ties) };
    if (await run({ action: "accept_document", targets: [doc], payload, tip })) onDone?.();
  };
  return (
    <form onSubmit={submit}>
      <p className="small">
        Accepts all {count} values read from {doc} in one act.{" "}
        {ties ? "The lots tie to the printed summary, so this accepts the account at its summary." : ""} The record keeps
        which values you accepted and what they were.
      </p>
      <Field label="How you verified">
        <TypeSelect value={type} onChange={setType} />
      </Field>
      <ActError error={error} />
      <Submit busy={busy} onCancel={onDone}>
        Accept {count} values
      </Submit>
    </form>
  );
}

// Sign a work area (or the California lens). Signing over open errors needs a waiver sentence (D14).
export function SignOffForm({ area, label, tip, openErrors, level, onDone }) {
  const { run, busy, error } = useAct();
  const [waiver, setWaiver] = useState("");
  const submit = async (e) => {
    e.preventDefault();
    const payload = waiver.trim() ? { waiver } : {};
    if (await run({ action: "sign_off", targets: [`area:${area}`], payload, tip })) onDone?.();
  };
  return (
    <form onSubmit={submit}>
      <p className="small">
        Signs every figure in {label} as it stands now. The sign-off reopens on its own if a covered figure changes.
      </p>
      {openErrors > 0 && (
        <Field label={`Waiver: ${openErrors} open error${openErrors > 1 ? "s" : ""} in this area`}
               hint="Say why you sign with them open. The errors and their estimated effects go on the sign-off.">
          <textarea rows={2} value={waiver} onChange={(e) => setWaiver(e.target.value)} />
        </Field>
      )}
      <ActError error={error} />
      <Submit busy={busy} disabled={openErrors > 0 && !waiver.trim()} onCancel={onDone}>
        Sign as {level}
      </Submit>
    </form>
  );
}

// The partner signs the return once, and in the same act approves the large adjustments, waivers (D10)
// and acceptances (D20).
export function ReleaseForm({ tip, preview, onDone }) {
  const { run, busy, error } = useAct();
  const submit = async (e) => {
    e.preventDefault();
    if (await run({ action: "partner_release", targets: ["return"], tip })) onDone?.();
  };
  const count = preview.adjustments.length + preview.waivers.length + preview.acceptances.length;
  return (
    <form onSubmit={submit}>
      {count > 0 ? (
        <div className="small">
          This release also signs:
          <ul className="plain">
            {preview.adjustments.map((a) => (
              <li key={a.event}>
                adjustment to {a.line}: {money(a.from)} → {money(a.to)} (federal {signed(a.effect.federal)}, California{" "}
                {signed(a.effect.california)})
              </li>
            ))}
            {preview.waivers.map((w) => (
              <li key={w.id}>
                waived in {w.area.replace(/_/g, " ")}: {w.id} (federal {signed(w.federal)}, California {signed(w.california)})
              </li>
            ))}
            {preview.acceptances.map((a) => (
              <li key={a.id}>
                accepted as is: {a.id}, “{a.decision}” (federal {signed(a.federal)}, California {signed(a.california)})
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="small">No adjustment, waiver or acceptance over $1,000 to sign with it.</p>
      )}
      <ActError error={error} />
      <Submit busy={busy} onCancel={onDone}>
        Release the return
      </Submit>
    </form>
  );
}

// Undo is a new act that reverses an old one. The old one stays in the record, marked undone.
export function UndoForm({ eventId, tip, onDone }) {
  const { run, busy, error } = useAct();
  const [reason, setReason] = useState("");
  const submit = async (e) => {
    e.preventDefault();
    if (await run({ action: "undo", targets: [`event:${eventId}`], reason, tip })) onDone?.();
  };
  return (
    <form onSubmit={submit} className="inline-form">
      <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why undo it" autoFocus />
      <ActError error={error} />
      <Submit busy={busy} disabled={!reason.trim()} onCancel={onDone}>
        Undo
      </Submit>
    </form>
  );
}

function signed(v) {
  return `${v > 0 ? "+" : ""}${money(v)}`;
}

// Attach a file as evidence. Files are stored by content hash; opening one later is a logged,
// cleared-only view, because a file cannot be masked (D13).
export function AttachForm({ targets, tip, onDone }) {
  const { refresh } = useApp();
  const [file, setFile] = useState(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const form = new FormData();
    form.append("file", file);
    form.append("targets", targets.join(","));
    form.append("note", note);
    form.append("base_tip", String(tip ?? 0));
    const res = await fetch("/api/attachments", { method: "POST", body: form, credentials: "same-origin" });
    const data = await res.json().catch(() => ({}));
    setBusy(false);
    if (!res.ok) return setError(Object.assign(new Error(data.detail || "Upload failed"), { status: res.status, data }));
    refresh();
    onDone?.();
  };
  return (
    <form onSubmit={submit}>
      <Field label="File" hint="Stored by its content hash. Opening it later is logged.">
        <input type="file" onChange={(e) => setFile(e.target.files[0] || null)} />
      </Field>
      <Field label="What it supports">
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. bank statement line for the 2021 purchase" />
      </Field>
      <ActError error={error} />
      <Submit busy={busy} disabled={!file} onCancel={onDone}>
        Attach
      </Submit>
    </form>
  );
}

// ---- filing (D23, D25) ------------------------------------------------------------

// Transmit the return as it stands. The server lists what still blocks it, in its own words.
export function TransmitForm({ tip, kind, blockers, onDone }) {
  const { run, busy, error } = useAct();
  const submit = async (e) => {
    e.preventDefault();
    if (await run({ action: "transmit", targets: ["return"], tip })) onDone?.();
  };
  return (
    <form onSubmit={submit}>
      <p className="small">
        Sends the {kind === "amended" ? "amended return" : "return"} as the clients signed it. The agency answers from its own
        records: it reads the SSNs on the return, not the checker's findings.
      </p>
      {blockers.length > 0 && (
        <ul className="small blockers">
          {blockers.map((b) => (
            <li key={b}>{b}</li>
          ))}
        </ul>
      )}
      <ActError error={error} />
      <Submit busy={busy} disabled={blockers.length > 0} onCancel={onDone}>
        Transmit
      </Submit>
    </form>
  );
}

// After filing the return is frozen; amending opens a full second round (D25).
export function AmendForm({ tip, onDone }) {
  const { run, busy, error } = useAct();
  const [reason, setReason] = useState("");
  const submit = async (e) => {
    e.preventDefault();
    if (await run({ action: "open_amendment", targets: ["return"], reason, tip })) onDone?.();
  };
  return (
    <form onSubmit={submit}>
      <p className="small">
        Lifts the freeze so the return can be amended on top. The return as filed stays on record. The amendment needs the
        sign-offs, the partner release and both 8879s again.
      </p>
      <Field label="Why amend">
        <textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} autoFocus />
      </Field>
      <ActError error={error} />
      <Submit busy={busy} disabled={!reason.trim()} onCancel={onDone}>
        Open the amendment
      </Submit>
    </form>
  );
}

// A client signs Form 8879 for the return they were shown. A later change reopens it.
export function Sign8879Form({ tip, onDone }) {
  const { run, busy, error } = useAct();
  const [agreed, setAgreed] = useState(false);
  const submit = async (e) => {
    e.preventDefault();
    if (await run({ action: "sign_8879", targets: ["return"], tip })) onDone?.();
  };
  return (
    <form onSubmit={submit}>
      <label className="check">
        <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
        <span>
          I have reviewed this return and I authorize the firm to file it electronically (Forms 8879 and FTB 8879). If the
          return changes, I will be asked to sign again.
        </span>
      </label>
      <ActError error={error} />
      <Submit busy={busy} disabled={!agreed} onCancel={onDone}>
        Sign the 8879
      </Submit>
    </form>
  );
}

// Take a person's SSN from a document that prints it. The record names the document, not the digits.
export function CorrectIdentityForm({ person, documents, finding, tip, onDone }) {
  const { run, busy, error } = useAct();
  const [doc, setDoc] = useState(documents[0]);
  const [reason, setReason] = useState("");
  const submit = async (e) => {
    e.preventDefault();
    const payload = { document: doc, ...(finding ? { finding } : {}) };
    if (await run({ action: "correct_identity", targets: [`household:${person}`], payload, reason, tip })) onDone?.();
  };
  return (
    <form onSubmit={submit}>
      <Field label="Use the number printed on" hint="The return will carry that document's number; the record keeps which document.">
        <select value={doc} onChange={(e) => setDoc(e.target.value)}>
          {documents.map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Why">
        <textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
      </Field>
      <ActError error={error} />
      <Submit busy={busy} disabled={!reason.trim()} onCancel={onDone}>
        Correct the number
      </Submit>
    </form>
  );
}

// ---- the notice (D24) -----------------------------------------------------------------

// The firm's answer to one item, and the evidence it rests on. Saving again replaces the draft.
export function NoticeResponseForm({ notice, item, tip, onDone }) {
  const { run, busy, error } = useAct();
  const offered = [...new Set([...(item.draft?.evidence || []), ...item.suggested])];
  const [text, setText] = useState(item.draft?.text || "");
  const [picked, setPicked] = useState(new Set(item.draft?.evidence || item.suggested));
  const toggle = (ref) => setPicked((s) => {
    const next = new Set(s);
    next.has(ref) ? next.delete(ref) : next.add(ref);
    return next;
  });
  const submit = async (e) => {
    e.preventDefault();
    const targets = [notice.ref, ...offered.filter((r) => picked.has(r))];
    if (await run({ action: "notice_response", targets, payload: { item: item.item, text }, tip })) onDone?.();
  };
  return (
    <form onSubmit={submit}>
      <Field label="Our answer">
        <textarea rows={4} value={text} onChange={(e) => setText(e.target.value)} autoFocus />
      </Field>
      <div className="field-row">
        <span className="field-label">Evidence to send (suggested from the item's words)</span>
        <div className="picks">
          {offered.map((r) => (
            <label key={r} className="check">
              <input type="checkbox" checked={picked.has(r)} onChange={() => toggle(r)} /> <code>{r}</code>
            </label>
          ))}
        </div>
      </div>
      <ActError error={error} />
      <Submit busy={busy} disabled={!text.trim()} onCancel={onDone}>
        Save the answer
      </Submit>
    </form>
  );
}

export function ReleaseNoticeForm({ notice, tip, onDone }) {
  const { run, busy, error } = useAct();
  const submit = async (e) => {
    e.preventDefault();
    if (await run({ action: "release_notice_response", targets: [notice.ref], tip })) onDone?.();
  };
  return (
    <form onSubmit={submit}>
      <p className="small">
        The examiner will see exactly this package, resolved against the return as filed, masked. Review notes and internal
        findings never leave. Once released it cannot be taken back.
      </p>
      <ActError error={error} />
      <Submit busy={busy} onCancel={onDone}>
        Release to the examiner
      </Submit>
    </form>
  );
}

// ---- the firm -------------------------------------------------------------------------

export function LogTimeForm({ buckets, tip, onDone }) {
  const { run, busy, error } = useAct();
  const [bucket, setBucket] = useState(buckets[0]);
  const [hours, setHours] = useState("");
  const [text, setText] = useState("");
  const submit = async (e) => {
    e.preventDefault();
    if (await run({ action: "log_time", targets: [`time:${bucket}`], payload: { hours: Number(hours), text }, tip })) onDone?.();
  };
  return (
    <form onSubmit={submit}>
      <Field label="Against">
        <select value={bucket} onChange={(e) => setBucket(e.target.value)}>
          {buckets.map((b) => (
            <option key={b} value={b}>
              {b.replace(/_/g, " ")}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Hours">
        <input type="number" step="0.25" min="0.25" max="12" value={hours} onChange={(e) => setHours(e.target.value)} />
      </Field>
      <Field label="What you did">
        <input value={text} onChange={(e) => setText(e.target.value)} />
      </Field>
      <ActError error={error} />
      <Submit busy={busy} disabled={!hours} onCancel={onDone}>
        Log time
      </Submit>
    </form>
  );
}

// Change one firm standard. Numbers stay numbers; lists are one entry per line.
export function StandardForm({ path, current, tip, onDone }) {
  const { run, busy, error } = useAct();
  const isList = Array.isArray(current);
  const isNumber = typeof current === "number";
  const [value, setValue] = useState(isList ? current.join("\n") : String(current));
  const [reason, setReason] = useState("");
  const submit = async (e) => {
    e.preventDefault();
    const parsed = isList ? value.split("\n").map((v) => v.trim()).filter(Boolean) : isNumber ? Number(value) : value;
    if (await run({ action: "set_standard", targets: [], payload: { path, value: parsed }, reason, tip })) onDone?.();
  };
  return (
    <form onSubmit={submit}>
      <Field label={path.replace(/_/g, " ")} hint={isList ? "One entry per line." : undefined}>
        {isList ? (
          <textarea rows={Math.min(10, current.length + 1)} value={value} onChange={(e) => setValue(e.target.value)} />
        ) : (
          <input type={isNumber ? "number" : "text"} value={value} onChange={(e) => setValue(e.target.value)} />
        )}
      </Field>
      <Field label="Why">
        <textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
      </Field>
      <ActError error={error} />
      <Submit busy={busy} disabled={!reason.trim()} onCancel={onDone}>
        Change the standard
      </Submit>
    </form>
  );
}

// A planning decision for 2026 (D32): which estimate method the firm uses, and the authority for it.
// The 90% method carries the projected 2026 California tax; the server works out the installments.
export function PlanDecisionForm({ planRef, tip, onDone }) {
  const { run, busy, error } = useAct();
  const [method, setMethod] = useState("projected");
  const [projected, setProjected] = useState("");
  const [authority, setAuthority] = useState("");
  const [reason, setReason] = useState("");
  const submit = async (e) => {
    e.preventDefault();
    const payload = method === "projected"
      ? { method, projected_2026_tax: Number(projected), decision: `Pay 90% of projected 2026 California tax of ${money(Number(projected))}`, authority }
      : { method, decision: "Pay the 110% safe harbor", authority };
    if (await run({ action: "judgment_call", targets: [planRef], payload, reason, tip })) onDone?.();
  };
  return (
    <form onSubmit={submit}>
      <Field label="Method">
        <select value={method} onChange={(e) => setMethod(e.target.value)}>
          <option value="projected">90% of projected 2026 California tax</option>
          <option value="safe_harbor">110% of 2025 California tax (safe harbor)</option>
        </select>
      </Field>
      {method === "projected" && (
        <Field label="Projected 2026 California tax" hint="California-source income only, after the move.">
          <input type="number" min="0" step="1" value={projected} onChange={(e) => setProjected(e.target.value)} autoFocus />
        </Field>
      )}
      <Field label="Authority relied on" hint="Required by the firm for every judgment call.">
        <input value={authority} onChange={(e) => setAuthority(e.target.value)} placeholder="e.g. R&TC 19136.3" />
      </Field>
      <Field label="Why">
        <textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
      </Field>
      <ActError error={error} />
      <Submit busy={busy} disabled={!authority.trim() || (method === "projected" && projected === "")} onCancel={onDone}>
        Record the method
      </Submit>
    </form>
  );
}
