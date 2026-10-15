// Search the whole file: lines, documents, read values, findings, client words, people's notes.
// The server matches on masked text, so a search cannot confirm a hidden number.
import { useApi } from "../api.js";
import { ErrorBox, Loading, Ref } from "../components/common.jsx";
import { dateTime, figure } from "../format.js";

const GROUPS = {
  lines: "Return lines", documents: "Documents", values: "Values read from documents", findings: "Checker findings",
  client: "What the client said", acts: "Notes, questions and answers",
};

export default function Search({ params, names, refreshKey }) {
  const q = params.q || "";
  const { data, error } = useApi(q.length >= 2 ? `/api/search?q=${encodeURIComponent(q)}` : null, refreshKey);
  if (q.length < 2) return <div className="page narrow"><p className="muted">Type at least two characters in the search box.</p></div>;
  if (error) return <ErrorBox error={error} />;
  if (!data) return <Loading />;
  const groups = Object.entries(GROUPS).filter(([g]) => data.groups[g]?.length);
  return (
    <div className="page narrow">
      <div className="page-head">
        <div>
          <h1>Search: “{q}”</h1>
          {groups.length === 0 && <p className="muted">Nothing found.</p>}
        </div>
      </div>
      {groups.map(([g, label]) => (
        <section key={g}>
          <h2>
            {label} <span className="muted small">{data.counts[g]}{data.counts[g] > data.groups[g].length ? `, first ${data.groups[g].length}` : ""}</span>
          </h2>
          <ul className="plain results">
            {data.groups[g].map((r) => (
              <li key={r.ref}>
                <Ref value={r.ref} /> <Result group={g} r={r} names={names} />
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

function Result({ group, r, names }) {
  switch (group) {
    case "lines":
      return <>{r.label} <span className="num muted">{figure(r.value, r.key)}</span></>;
    case "documents":
      return <>{r.title}</>;
    case "values":
      return <>{r.document} page {r.page}, {r.field}: <span className="num">{String(r.value)}</span></>;
    case "findings":
      return <>{r.title} <span className="muted small">{r.status}</span></>;
    case "client":
      return <>“{r.text}” <span className="muted small">{r.from}</span></>;
    default:
      return <>{r.text} <span className="muted small">{names[r.by] || r.by} · {dateTime(r.at)}</span></>;
  }
}
