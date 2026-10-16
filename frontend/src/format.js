// Display helpers. Formatting only; no tax logic lives here.

// Whole dollars with thousands separators; negatives in parentheses, the way CPAs read them.
export function money(value, { cents = false } = {}) {
  if (value === null || value === undefined || value === "") return "";
  if (typeof value !== "number") return String(value);
  const abs = Math.abs(value).toLocaleString("en-US", {
    minimumFractionDigits: cents ? 2 : 0,
    maximumFractionDigits: cents ? 2 : 0,
  });
  return value < 0 ? `(${abs})` : abs;
}

// A line value: lots are in cents, ratios stay as given, text passes through.
export function figure(value, key = "") {
  if (typeof value !== "number") return value ?? "";
  if (Math.abs(value) < 1 && value !== 0) return value.toString();
  return money(value, { cents: key.startsWith("F8949.") && !Number.isInteger(value) });
}

export function change(now, before) {
  if (typeof now !== "number" || typeof before !== "number") return null;
  const diff = now - before;
  const pct = before === 0 ? null : (diff / Math.abs(before)) * 100;
  return { diff, pct };
}

export function pct(p) {
  if (p === null || p === undefined) return "new";
  const sign = p > 0 ? "+" : "";
  return `${sign}${Math.round(p)}%`;
}

// Packet dates display as recorded (UTC), so 2026-01-20T04:00Z is January 20 wherever you are.
export function date(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
}

export function dateTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export function initials(name = "") {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

// A label for a key from the server, or the key itself. Only the map's own keys count, so a value
// such as "__proto__" can never pull an object out of the map and into the screen.
export function labelFor(map, key) {
  return Object.hasOwn(map, key) ? map[key] : String(key ?? "");
}

export const ROLE_LABEL = {
  preparer: "Preparer",
  reviewer: "Reviewer",
  partner: "Partner",
  firm_administrator: "Administrator",
  quality_reviewer: "Quality reviewer",
  client: "Client",
  examiner: "IRS examiner",
};

// Machine states (D2): what the software can say. It never says "verified".
export const MACHINE = {
  ties: { label: "Ties to page", tone: "ties" },
  disagreement: { label: "Not on page", tone: "bad" },
  conflict: { label: "Conflict", tone: "warn" },
  stale: { label: "Newer evidence", tone: "stale" },
  open_item: { label: "Open item", tone: "open" },
  prompt: { label: "Needs a call", tone: "prompt" },
  variance: { label: "Swing vs 2024", tone: "muted" },
  not_read: { label: "Not read", tone: "bad" },
};

export const SEVERITY_LABEL = { error: "Error", warning: "Warning", info: "Info" };

export const VERIFICATION_LABEL = {
  agreed_to_source_document: "agreed to source",
  recalculated: "recalculated",
  confirmed_with_client: "confirmed with client",
  agreed_to_prior_year: "agreed to prior year",
  agreed_to_third_party_record: "agreed to third-party record",
};
