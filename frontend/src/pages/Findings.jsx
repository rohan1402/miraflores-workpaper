// What the checker found, grouped by rule. Findings are derived on every read, never stored.
import { useState } from "react";
import { useApi } from "../api.js";
import { ErrorBox, Estimate, Loading } from "../components/common.jsx";
import FindingCard from "../components/FindingCard.jsx";
import { money } from "../format.js";
import { href } from "../router.js";

const SEVERITIES = { all: "All", error: "Errors", warning: "Warnings", info: "Info" };

export default function Findings({ params, refreshKey }) {
  const area = params.area;
  const { data, error } = useApi(`/api/findings${area ? `?area=${encodeURIComponent(area)}` : ""}`, refreshKey);
  const [severity, setSeverity] = useState("error");
  if (error) return <ErrorBox error={error} />;
  if (!data) return <Loading />;
  const shown = data.findings.filter((f) => severity === "all" || f.severity === severity);
  const byRule = Object.entries(data.rules)
    .map(([rule, title]) => [rule, title, shown.filter((f) => f.rule === rule)])
    .filter(([, , list]) => list.length);
  const net = data.net_effect;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="crumbs">
            <a href={href.home()}>The return</a> ›{area && <a href={href.area(area)}> {area.replace(/_/g, " ")}</a>}
          </div>
          <h1>Checker findings{area ? `: ${area.replace(/_/g, " ")}` : ""}</h1>
          <p className="muted">
            Checks that re-read the printed pages and the agency records without trusting the engine. Machine states only:
            nothing here is “verified”.
          </p>
        </div>
        {!area && (
          <div className="card net">
            <span className="muted small">All open corrections, each line built once</span>
            <span>
              Federal <strong className="num">{money(net.federal)}</strong> · California{" "}
              <strong className="num">{money(net.california)}</strong> <Estimate />
            </span>
          </div>
        )}
      </div>

      <div className="filters">
        {Object.entries(SEVERITIES).map(([key, label]) => (
          <button key={key} className={severity === key ? "on" : ""} onClick={() => setSeverity(key)}>
            {label} <span className="muted">{data.findings.filter((f) => key === "all" || f.severity === key).length}</span>
          </button>
        ))}
      </div>

      {byRule.map(([rule, title, list]) => (
        <section key={rule}>
          <h2>
            <span className="muted">{rule}</span> {title} <span className="muted small">{list.length}</span>
          </h2>
          {list.map((f) => (
            <FindingCard key={f.id} finding={f} tip={data.meta.tip} />
          ))}
        </section>
      ))}
      {byRule.length === 0 && <p className="muted">Nothing at this severity.</p>}
    </div>
  );
}
