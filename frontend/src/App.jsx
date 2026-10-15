// The shell: who is acting (role switcher), where you are (hash routes), and live updates.
import { useCallback, useEffect, useMemo, useState } from "react";
import { getJSON, postJSON, useApi } from "./api.js";
import { describeEvent } from "./events.js";
import { ROLE_LABEL, initials } from "./format.js";
import { href, useRoute } from "./router.js";
import { Counts } from "./components/common.jsx";
import Home from "./pages/Home.jsx";
import Area from "./pages/Area.jsx";
import Line from "./pages/Line.jsx";
import Document from "./pages/Document.jsx";
import Documents from "./pages/Documents.jsx";
import Findings from "./pages/Findings.jsx";
import Since from "./pages/Since.jsx";
import Questions from "./pages/Questions.jsx";

export default function App() {
  const route = useRoute();
  const [me, setMe] = useState(null);
  const [checked, setChecked] = useState(false);
  const [people, setPeople] = useState([]);
  const [refreshKey, setRefreshKey] = useState(0);
  const [live, setLive] = useState("off");
  const [notices, setNotices] = useState([]);

  const names = useMemo(() => Object.fromEntries(people.map((p) => [p.id, p.name])), [people]);

  useEffect(() => {
    getJSON("/api/people").then(setPeople);
    getJSON("/api/me")
      .then(setMe)
      .catch(() => setMe(null))
      .finally(() => setChecked(true));
  }, []);

  const choose = useCallback(async (personId) => {
    setMe(await postJSON("/api/session", { person: personId }));
    setRefreshKey((k) => k + 1);
    window.location.hash = "#/";
  }, []);

  // Live updates (D15): the server pushes each new event; the screen refetches and says who did what.
  useEffect(() => {
    if (!me) return undefined;
    const source = new EventSource("/api/stream");
    source.onopen = () => setLive("on");
    source.onerror = () => setLive("reconnecting");
    source.addEventListener("wp-event", (msg) => {
      const event = JSON.parse(msg.data);
      setRefreshKey((k) => k + 1);
      if (event.actor !== me.person.id) {
        const notice = { id: event.id, text: describeEvent(event, names) };
        setNotices((n) => [...n.slice(-3), notice]);
        setTimeout(() => setNotices((n) => n.filter((x) => x.id !== notice.id)), 6000);
      }
    });
    return () => source.close();
  }, [me, names]);

  if (!checked) return null;
  if (!me) return <Welcome people={people} onChoose={choose} />;

  const surface = me.config.surface;
  return (
    <div className="app">
      <TopBar me={me} people={people} onChoose={choose} live={live} refreshKey={refreshKey} />
      <div className="body">
        {surface === "questions" ? null : <Nav route={route} refreshKey={refreshKey} />}
        <main className="main">
          <Page route={route} me={me} names={names} refreshKey={refreshKey} />
        </main>
      </div>
      <div className="notices">
        {notices.map((n) => (
          <div key={n.id} className="notice">
            {n.text}
          </div>
        ))}
      </div>
    </div>
  );
}

function Page({ route, me, names, refreshKey }) {
  const props = { me, names, refreshKey, params: route.params };
  if (me.config.surface === "questions") return <Questions {...props} />;
  switch (route.name) {
    case "area":
      return <Area id={route.id} {...props} />;
    case "line":
      return <Line lineKey={route.id} {...props} />;
    case "doc":
      return <Document docId={route.id} {...props} />;
    case "documents":
      return <Documents {...props} />;
    case "findings":
      return <Findings {...props} />;
    case "since":
      return <Since {...props} />;
    case "questions":
      return <Questions {...props} />;
    default:
      return <Home {...props} />;
  }
}

function TopBar({ me, people, onChoose, live, refreshKey }) {
  const since = useApi(me.config.surface === "questions" ? null : "/api/since", refreshKey);
  const unseen = since.data?.events.length || 0;
  return (
    <header className="topbar">
      <a className="brand" href={href.home()}>
        <span className="brand-mark">W</span>
        <span>
          <strong>Okafor-Lindqvist</strong> <span className="muted">2025 return · CL-20417</span>
        </span>
      </a>
      <div className="topbar-right">
        {me.config.surface !== "questions" && (
          <a className={`since-link ${unseen ? "has" : ""}`} href={href.since()} title="Changes by others since you last looked">
            Since I last looked {unseen ? <span className="pill">{unseen}</span> : <span className="muted">· nothing new</span>}
          </a>
        )}
        <span className={`live live-${live}`} title={`Live updates: ${live}`}>
          <span className="live-dot" /> {live === "on" ? "Live" : live}
        </span>
        <RoleSwitcher me={me} people={people} onChoose={onChoose} />
      </div>
    </header>
  );
}

function RoleSwitcher({ me, people, onChoose }) {
  return (
    <label className="switcher" title="Role switcher: who is acting. Roles are enforced on the server.">
      <span className="avatar">{initials(me.person.name)}</span>
      <select value={me.person.id} onChange={(e) => onChoose(e.target.value)}>
        {people.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name} · {ROLE_LABEL[p.role] || p.role}
            {p.role !== "client" && p.role !== "examiner" && !p.clearance ? " · no clearance" : ""}
          </option>
        ))}
      </select>
    </label>
  );
}

function Nav({ route, refreshKey }) {
  const home = useApi("/api/return", refreshKey);
  const areas = home.data?.areas || [];
  const at = (name, id) => route.name === name && (id === undefined || route.id === id);
  return (
    <nav className="nav">
      <a className={at("home") ? "active" : ""} href={href.home()}>
        The return
      </a>
      <div className="nav-group">Work areas</div>
      {areas.map((a) => (
        <a key={a.id} className={`${at("area", a.id) ? "active" : ""} ${a.lens ? "lens" : ""}`} href={href.area(a.id)}>
          <span className="ticks">
            <Tick status={a.preparer.status} />
            <Tick status={a.reviewer.status} />
          </span>
          <span className="nav-label">{a.label}</span>
          <Counts counts={a.open_findings} compact />
        </a>
      ))}
      <div className="nav-group">Evidence</div>
      <a className={at("documents") || at("doc") ? "active" : ""} href={href.documents()}>
        Documents
      </a>
      <a className={at("findings") ? "active" : ""} href={href.findings()}>
        Checker findings
      </a>
      <a className={at("questions") ? "active" : ""} href={href.questions()}>
        Client questions
      </a>
    </nav>
  );
}

export function Tick({ status }) {
  const label = { signed: "Signed", reopened: "Reopened: a covered value changed", unsigned: "Not signed" }[status];
  const mark = { signed: "✓", reopened: "↺", unsigned: "" }[status];
  return (
    <span className={`tick tick-${status}`} title={label}>
      {mark}
    </span>
  );
}

function Welcome({ people, onChoose }) {
  const groups = [
    ["Firm", people.filter((p) => !["client", "examiner"].includes(p.role))],
    ["Client", people.filter((p) => p.role === "client")],
    ["After filing", people.filter((p) => p.role === "examiner")],
  ];
  return (
    <div className="welcome">
      <div className="welcome-card">
        <div className="brand-mark big">W</div>
        <h1>Okafor-Lindqvist · 2025 workpaper</h1>
        <p className="muted">
          Pick who you are. Each person sees the same return; what they can do, and what is masked, is enforced on the server.
        </p>
        {groups.map(([title, list]) => (
          <div key={title} className="welcome-group">
            <div className="nav-group">{title}</div>
            {list.map((p) => (
              <button key={p.id} className="person" onClick={() => onChoose(p.id)}>
                <span className="avatar">{initials(p.name)}</span>
                <span>
                  <strong>{p.name}</strong>
                  <span className="muted"> · {ROLE_LABEL[p.role] || p.role}</span>
                  {p.role !== "client" && p.role !== "examiner" && !p.clearance && <span className="tag">no sensitive-data clearance</span>}
                </span>
              </button>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
