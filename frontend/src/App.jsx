// The shell: who is acting (role switcher), where you are (hash routes), and live updates.
import { useCallback, useEffect, useMemo, useState } from "react";
import { AppContext, getJSON, postJSON, useApi } from "./api.js";
import { describeEvent } from "./events.js";
import { ROLE_LABEL, date, initials } from "./format.js";
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
import Timeline from "./pages/Timeline.jsx";
import Filing from "./pages/Filing.jsx";
import YourReturn from "./pages/YourReturn.jsx";
import Notice from "./pages/Notice.jsx";
import Examiner from "./pages/Examiner.jsx";
import Firm from "./pages/Firm.jsx";
import Search from "./pages/Search.jsx";
import RollForward from "./pages/RollForward.jsx";

export default function App() {
  const route = useRoute();
  const [me, setMe] = useState(null);
  const [checked, setChecked] = useState(false);
  const [people, setPeople] = useState([]);
  const [refreshKey, setRefreshKey] = useState(0);
  const [live, setLive] = useState("off");
  const [notices, setNotices] = useState([]);
  const [asOf, setAsOf] = useState(null); // replay date (YYYY-MM-DD); null = now

  const names = useMemo(() => Object.fromEntries(people.map((p) => [p.id, p.name])), [people]);
  const refresh = useCallback(() => setRefreshKey((k) => k + 1), []);
  const context = useMemo(() => ({ me, names, asOf, setAsOf, refresh }), [me, names, asOf, refresh]);

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
    <AppContext.Provider value={context}>
    <div className="app">
      <TopBar me={me} people={people} onChoose={choose} live={live} refreshKey={refreshKey} />
      {asOf && (
        <div className="replay-banner">
          Replaying the season as of <strong>{date(`${asOf}T12:00:00Z`)}</strong>: the version, documents and people's acts as
          they stood that day. Read only.
          <button className="link" onClick={() => setAsOf(null)}>
            Back to now
          </button>
        </div>
      )}
      <div className="body">
        {surface === "questions" && <ClientNav route={route} />}
        {surface === "workpaper" || surface === "standards" ? <Nav route={route} surface={surface} refreshKey={refreshKey} /> : null}
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
    </AppContext.Provider>
  );
}

function Page({ route, me, names, refreshKey }) {
  const props = { me, names, refreshKey, params: route.params };
  // The clients have their own surface; the examiner sees only the released response (D24).
  if (me.config.surface === "questions") return route.name === "your-return" ? <YourReturn {...props} /> : <Questions {...props} />;
  if (me.config.surface === "frozen") return <Examiner {...props} />;
  switch (route.name) {
    case "return":
      return <Home {...props} />;
    case "filing":
      return <Filing {...props} />;
    case "your-return":
      return <YourReturn {...props} />;
    case "notice":
      return <Notice {...props} />;
    case "examiner":
      return <Examiner {...props} />;
    case "firm":
      return <Firm {...props} />;
    case "search":
      return <Search {...props} />;
    case "roll-forward":
      return <RollForward {...props} />;
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
    case "timeline":
      return <Timeline {...props} />;
    default:
      // The administrator's home is the firm's standards (D1); the return is one click away.
      return me.config.surface === "standards" ? <Firm {...props} /> : <Home {...props} />;
  }
}

function TopBar({ me, people, onChoose, live, refreshKey }) {
  const staff = !["questions", "frozen"].includes(me.config.surface);
  const since = useApi(staff ? "/api/since" : null, refreshKey);
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
        {staff && <SearchBox />}
        {staff && (
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

function SearchBox() {
  const [q, setQ] = useState("");
  const go = (e) => {
    e.preventDefault();
    if (q.trim().length >= 2) window.location.hash = href.search(q.trim());
  };
  return (
    <form className="searchbox" onSubmit={go} role="search">
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search the file" aria-label="Search the file" />
    </form>
  );
}

function ClientNav({ route }) {
  return (
    <nav className="nav client-nav">
      <a className={route.name !== "your-return" ? "active" : ""} href={href.questions()}>
        Questions
      </a>
      <a className={route.name === "your-return" ? "active" : ""} href={href.yourReturn()}>
        Your return
      </a>
    </nav>
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

function Nav({ route, surface, refreshKey }) {
  const home = useApi("/api/return", refreshKey);
  const areas = home.data?.areas || [];
  // The administrator's home is the firm page, so "home" lights up Firm for her.
  const name = route.name === "home" && surface === "standards" ? "firm" : route.name;
  const at = (n, id) => name === n && (id === undefined || route.id === id);
  return (
    <nav className="nav">
      <a className={at("home") || at("return") ? "active" : ""} href={href.theReturn()}>
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
      <div className="nav-group">Season</div>
      <a className={at("timeline") ? "active" : ""} href={href.timeline()}>
        Timeline and replay
      </a>
      <a className={at("filing") ? "active" : ""} href={href.filing()}>
        Filing <span className="muted small">{home.data?.filing?.stage}</span>
      </a>
      <a className={at("your-return") ? "active" : ""} href={href.yourReturn()}>
        The clients' page
      </a>
      <a className={at("notice") ? "active" : ""} href={href.notice()}>
        Notices
      </a>
      <a className={at("roll-forward") ? "active" : ""} href={href.rollForward()}>
        2026 opening
      </a>
      <div className="nav-group">Firm</div>
      <a className={at("firm") ? "active" : ""} href={href.firm()}>
        Time, standards, view log
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
