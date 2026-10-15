// Everything people did to one line, document or finding, oldest first, with undo.
import { useState } from "react";
import { useApi, useApp } from "../api.js";
import { useCan } from "./Act.jsx";
import { UndoForm } from "./Forms.jsx";
import { describeEvent } from "../events.js";
import { dateTime } from "../format.js";

export default function History({ refId, tip, refreshKey }) {
  const { data } = useApi(`/api/history?ref=${encodeURIComponent(refId)}`, refreshKey);
  if (!data || data.length === 0) return null;
  return (
    <section>
      <h2>What people did here</h2>
      <ol className="timeline">
        {data.map((e) => (
          <HistoryItem key={e.id} event={e} tip={tip} />
        ))}
      </ol>
    </section>
  );
}

function HistoryItem({ event: e, tip }) {
  const { me, names } = useApp();
  const can = useCan();
  const [undoing, setUndoing] = useState(false);
  // Firm rule mirrored for the button only (the server decides): the actor, a reviewer or the partner.
  const mayUndo = can("undo") && e.action !== "undo" && !e.undone
    && (e.actor === me.person.id || ["reviewer", "partner"].includes(me.person.role));
  return (
    <li className={e.undone ? "undone" : ""}>
      <span className="muted small">
        #{e.id} · {dateTime(e.at)}
        {e.undone && <span className="tag">undone</span>}
      </span>
      <span>{describeEvent(e, names)}</span>
      {e.payload?.text && <span className="small">“{e.payload.text}”</span>}
      {e.payload?.waiver && <span className="small">Waiver: “{e.payload.waiver}”</span>}
      {e.payload?.authority && <span className="small">Authority: {e.payload.authority}</span>}
      {e.reason && <span className="muted small">Why: {e.reason}</span>}
      {e.action === "attach_evidence" && e.payload?.sha256 && (
        me.clearance ? (
          <a className="small" href={`/api/attachments/${e.payload.sha256}`} target="_blank" rel="noreferrer">
            Open {e.payload.file_name} (the view is logged)
          </a>
        ) : (
          <span className="small muted">File held by hash; opening it needs sensitive-data clearance.</span>
        )
      )}
      {mayUndo && !undoing && (
        <button className="link small" onClick={() => setUndoing(true)}>
          Undo
        </button>
      )}
      {undoing && <UndoForm eventId={e.id} tip={tip} onDone={() => setUndoing(false)} />}
    </li>
  );
}
