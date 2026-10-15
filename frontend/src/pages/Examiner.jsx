// The IRS examiner's view (D24): only the response the partner released, as it was released, masked.
// No workpaper, no internal notes, no live updates.
import { useApi } from "../api.js";
import { ErrorBox, Loading } from "../components/common.jsx";
import ResponsePackage from "../components/ResponsePackage.jsx";
import { date, dateTime } from "../format.js";

export default function Examiner({ refreshKey }) {
  const { data, error } = useApi("/api/examiner", refreshKey);
  if (error) return <ErrorBox error={error} />;
  if (!data) return <Loading />;
  return (
    <div className="page narrow">
      <div className="page-head">
        <div>
          <h1>Response to examination</h1>
          <p className="muted">What the firm released for the 2025 return. Each figure is shown as filed, with the pages it came from.</p>
        </div>
      </div>
      {data.released.length === 0 && <p className="muted">The firm has not released a response yet.</p>}
      {data.released.map((r) => (
        <div key={r.released_event}>
          <p className="small">
            {r.type}, dated {date(`${r.dated}T12:00:00Z`)}. Released {dateTime(r.released_at)}. Return as filed: federal
            submission {r.filed_submission}.{" "}
            <a href="/api/examiner/export" download>
              Download as one file
            </a>
          </p>
          <ResponsePackage pkg={r} />
        </div>
      ))}
    </div>
  );
}
