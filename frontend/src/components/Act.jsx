// Acting on the workpaper. Every act is a POST of what the person chose; the server computes the
// rest, applies the firm's rules (403, 422) and refuses a stale view (409). Nothing here decides.
import { useState } from "react";
import { postJSON, useApp } from "../api.js";
import { describeEvent } from "../events.js";

// May this person do this here? No acts while replaying the past, and only the role's verbs.
export function useCan() {
  const { me, asOf } = useApp();
  return (verb) => !asOf && Boolean(me?.verbs.includes(verb));
}

export function useAct() {
  const { refresh } = useApp();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function run({ action, targets = [], payload = {}, reason = null, tip }) {
    setBusy(true);
    setError(null);
    try {
      const result = await postJSON("/api/actions", { action, targets, payload, reason, base_tip: tip ?? 0 });
      refresh();
      return result;
    } catch (e) {
      setError(e);
      return null;
    } finally {
      setBusy(false);
    }
  }
  return { run, busy, error, clearError: () => setError(null) };
}

// What the server said no to, in its words. A 409 shows the act that landed first.
export function ActError({ error }) {
  const { names, refresh } = useApp();
  if (!error) return null;
  if (error.status === 409) {
    return (
      <div className="act-error conflict">
        Someone acted first: <strong>{describeEvent(error.data.conflict, names)}</strong>. Look again before acting.{" "}
        <button className="link" onClick={refresh}>
          Show me
        </button>
      </div>
    );
  }
  const reasons = error.data?.refused || [error.message];
  return (
    <div className="act-error">
      {reasons.map((r) => (
        <div key={r}>{r}</div>
      ))}
    </div>
  );
}

// A row of verbs; each opens its form underneath. Only one form open at a time.
export function ActionBar({ actions }) {
  const shown = actions.filter((a) => a.allowed !== false);
  const [open, setOpen] = useState(null);
  if (!shown.length) return null;
  const current = shown.find((a) => a.key === open);
  return (
    <div className="action-bar">
      <div className="action-buttons">
        {shown.map((a) => (
          <button key={a.key} className={`act-btn ${open === a.key ? "on" : ""} ${a.primary ? "primary-outline" : ""}`}
                  onClick={() => setOpen(open === a.key ? null : a.key)}>
            {a.label}
          </button>
        ))}
      </div>
      {current && <div className="action-form">{current.render(() => setOpen(null))}</div>}
    </div>
  );
}

export function Field({ label, hint, children }) {
  return (
    <label className="field-row">
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  );
}

export const VERIFICATION_TYPES = [
  ["agreed_to_source_document", "Agreed to source document"],
  ["recalculated", "Recalculated"],
  ["confirmed_with_client", "Confirmed with client"],
  ["agreed_to_prior_year", "Agreed to prior year"],
  ["agreed_to_third_party_record", "Agreed to third-party record"],
];
