// A tiny hash router: #/area/business, #/line/F1040.26, #/doc/D09?page=1&ev=ev-0047.
// Hash routes need no server configuration, so FastAPI can serve one index.html.
import { useEffect, useState } from "react";

export function parseHash(hash) {
  const [path, query = ""] = (hash.replace(/^#/, "") || "/").split("?");
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  return { name: parts[0] || "home", id: parts[1] || null, params: Object.fromEntries(new URLSearchParams(query)) };
}

export function useRoute() {
  const [route, setRoute] = useState(() => parseHash(window.location.hash));
  useEffect(() => {
    const onChange = () => {
      setRoute(parseHash(window.location.hash));
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

export const href = {
  home: () => "#/",
  area: (id) => `#/area/${encodeURIComponent(id)}`,
  line: (key) => `#/line/${encodeURIComponent(key)}`,
  doc: (id, page, ev) =>
    `#/doc/${encodeURIComponent(id)}` + (page ? `?page=${page}` + (ev ? `&ev=${encodeURIComponent(ev)}` : "") : ""),
  documents: () => "#/documents",
  findings: (area) => "#/findings" + (area ? `?area=${encodeURIComponent(area)}` : ""),
  since: () => "#/since",
  questions: () => "#/questions",
  timeline: () => "#/timeline",
};

// Turn any reference the server sends into a link, when there is a screen for it.
export function linkFor(ref) {
  if (!ref) return null;
  if (ref.startsWith("line:")) return href.line(ref.slice(5));
  if (ref.startsWith("area:")) return href.area(ref.slice(5));
  if (/^D\d\d$/.test(ref)) return href.doc(ref);
  const page = ref.match(/^doc:(D\d\d)#page(\d+)$/);
  if (page) return href.doc(page[1], page[2]);
  return null;
}
