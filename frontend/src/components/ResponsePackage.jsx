// A notice response as the examiner reads it (D24): each item, the firm's answer, and the evidence,
// resolved against the return as filed. Used for the partner's preview and the examiner's view.
import { dateTime, figure, money } from "../format.js";

export default function ResponsePackage({ pkg }) {
  return (
    <div className="package">
      {pkg.items.map((item) => (
        <section key={item.item} className="card">
          <h3>Item {item.item + 1}</h3>
          <p className="examined">{item.examined}</p>
          <h4>Our answer</h4>
          <p>{item.answer || <span className="muted">No answer yet.</span>}</p>
          {item.evidence.map((ev) => (
            <Evidence key={ev.ref} ev={ev} />
          ))}
        </section>
      ))}
    </div>
  );
}

function Evidence({ ev }) {
  if (ev.kind === "line") {
    return (
      <div className="evidence">
        <div>
          <code>{ev.key}</code> {ev.label}: <strong className="num">{figure(ev.as_filed, ev.key)}</strong> as filed
        </div>
        {ev.adjustments.map((a, i) => (
          <div key={i} className="small">
            Adjusted from {money(a.from)} to {money(a.to)}: {a.reason}
          </div>
        ))}
        {ev.inputs.length > 0 && (
          <div className="small muted">Built from {ev.inputs.map((i) => `${i.key} ${money(i.value)}`).join(", ")}</div>
        )}
        {ev.sources.length > 0 && (
          <ul className="plain small">
            {ev.sources.map((s) => (
              <li key={s.ref}>
                <code>{s.ref}</code>{" "}
                {s.kind === "value" ? `${s.document} page ${s.page}, ${s.field}: ${s.value}` : s.kind === "client" ? `client: “${s.text}”` : s.kind}
              </li>
            ))}
          </ul>
        )}
        {ev.verified.length > 0 && (
          <div className="small">
            Verified: {ev.verified.map((v) => `${v.type.replace(/_/g, " ")} by ${v.by} (${dateTime(v.at)})`).join("; ")}
          </div>
        )}
      </div>
    );
  }
  if (ev.kind === "document") {
    return (
      <details className="evidence">
        <summary>
          <code>{ev.ref}</code> {ev.title}
        </summary>
        {ev.pages.map((p) => (
          <pre key={p.page} className="page-text small">
            Page {p.page}: {p.text}
          </pre>
        ))}
      </details>
    );
  }
  if (ev.kind === "client") {
    return (
      <div className="evidence small">
        <code>{ev.ref}</code> client, {ev.from}: “{ev.text}”
      </div>
    );
  }
  if (ev.kind === "attachment") {
    return (
      <div className="evidence small">
        Attached file {ev.file_name} (sha256 {String(ev.sha256).slice(0, 12)}…){ev.note ? `: ${ev.note}` : ""}
      </div>
    );
  }
  return <div className="evidence small muted">{ev.ref}: not in the return as filed.</div>;
}
