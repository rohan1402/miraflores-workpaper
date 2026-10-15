// Every document: where it landed, its disposition, and what is open on it (D2: disposition first).
import { useState } from "react";
import { useApi } from "../api.js";
import { ErrorBox, Loading } from "../components/common.jsx";
import { date } from "../format.js";
import { href } from "../router.js";

const FILTERS = {
  all: { label: "All", test: () => true },
  open: { label: "With open findings", test: (d) => d.open_findings > 0 },
  nowhere: { label: "Landed nowhere", test: (d) => d.lines === 0 },
  partial: { label: "Not fully read", test: (d) => d.extraction !== "extracted" },
  undispositioned: { label: "No disposition yet", test: (d) => !d.disposition },
};

export default function Documents({ refreshKey }) {
  const { data, error } = useApi("/api/documents", refreshKey);
  const [filter, setFilter] = useState("all");
  if (error) return <ErrorBox error={error} />;
  if (!data) return <Loading />;
  const shown = data.filter(FILTERS[filter].test);
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Documents</h1>
          <p className="muted">{data.length} documents as delivered. Every document lands somewhere, or says why not.</p>
        </div>
      </div>
      <div className="filters">
        {Object.entries(FILTERS).map(([key, f]) => (
          <button key={key} className={filter === key ? "on" : ""} onClick={() => setFilter(key)}>
            {f.label} <span className="muted">{data.filter(f.test).length}</span>
          </button>
        ))}
      </div>
      <table className="lines">
        <thead>
          <tr>
            <th>ID</th>
            <th>Document</th>
            <th>Received</th>
            <th>Read</th>
            <th>Disposition</th>
            <th className="num">Lines</th>
            <th className="num">Open</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((d) => (
            <tr key={d.id} className="clickable" onClick={() => (window.location.hash = href.doc(d.id))}>
              <td className="key">
                <a href={href.doc(d.id)}>{d.id}</a>
              </td>
              <td>
                {d.title}
                {d.corrected && <span className="tag warn">corrected</span>}
                <div className="muted small">{d.owners.map((o) => o.replace(/_/g, " ")).join(", ")}</div>
              </td>
              <td className="muted">{date(d.received_at)}</td>
              <td className={d.extraction !== "extracted" ? "warn" : "muted"}>{d.extraction.replace("_", " ")}</td>
              <td>{d.disposition ? d.disposition.value : <span className="muted">—</span>}</td>
              <td className={`num ${d.lines === 0 ? "warn" : ""}`}>{d.lines}</td>
              <td className="num">{d.open_findings || ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
