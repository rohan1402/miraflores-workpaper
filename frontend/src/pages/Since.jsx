// "Since I last looked": what others did after this person's last-seen mark. It survives closing the laptop.
import { useState } from "react";
import { postJSON, useApi } from "../api.js";
import { ErrorBox, Loading, Ref } from "../components/common.jsx";
import { describeEvent } from "../events.js";
import { dateTime } from "../format.js";

export default function Since({ names, refreshKey }) {
  const [bump, setBump] = useState(0);
  const { data, error } = useApi("/api/since", `${refreshKey}-${bump}`);
  if (error) return <ErrorBox error={error} />;
  if (!data) return <Loading />;
  const markSeen = async () => {
    await postJSON("/api/seen", { event_id: data.tip });
    setBump((b) => b + 1);
  };
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Since I last looked</h1>
          <p className="muted">
            Changes by others after event {data.last_seen}. Unmask records are in the view log, not here.
          </p>
        </div>
        {data.events.length > 0 && (
          <button className="primary" onClick={markSeen}>
            Mark all as seen
          </button>
        )}
      </div>
      {data.events.length === 0 ? (
        <p className="muted">Nothing new.</p>
      ) : (
        <ol className="timeline">
          {data.events.map((e) => (
            <li key={e.id}>
              <span className="muted small">
                #{e.id} · {dateTime(e.at)}
              </span>
              <span>{describeEvent(e, names)}</span>
              {e.reason && <span className="muted small">“{e.reason}”</span>}
              <span className="refs">
                {e.targets.map((t) => (
                  <Ref key={t} value={t} />
                ))}
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
