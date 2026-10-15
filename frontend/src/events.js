// One sentence per event, for live notices and "since I last looked".
import { money } from "./format.js";

const strip = (t) => t.replace(/^line:/, "").replace(/^area:/, "");

export function describeEvent(e, names = {}) {
  const who = names[e.actor] || e.actor;
  const t = (e.targets || []).map(strip).join(", ");
  const p = e.payload || {};
  switch (e.action) {
    case "adjust":
      return `${who} adjusted ${t} from ${money(p.from)} to ${money(p.to)}`;
    case "sign_off":
      return `${who} signed ${t} as ${p.level}${p.waiver ? " with a waiver" : ""}`;
    case "partner_release":
      return `${who} released the return`;
    case "approve_adjustment":
      return `${who} approved adjustment ${t}`;
    case "verify":
      return `${who} verified ${t}`;
    case "accept_document":
      return `${who} accepted ${t}`;
    case "disposition":
      return `${who} marked ${t} ${p.disposition}`;
    case "note":
      return `${who} left a note on ${t}`;
    case "review_note":
      return `${who} opened a review note on ${t}`;
    case "resolve_review_note":
      return `${who} resolved review note ${t}`;
    case "question":
      return `${who} asked ${p.to === "client" ? "the client" : names[p.to] || p.to} a question`;
    case "answer":
      return `${who} answered a question`;
    case "attach_evidence":
      return `${who} attached ${p.file_name || "evidence"} to ${t}`;
    case "judgment_call":
      return `${who} recorded a judgment call on ${t}`;
    case "undo":
      return `${who} undid ${t}`;
    case "set_standard":
      return `${who} changed the firm standard ${p.path}`;
    default:
      return `${who}: ${e.action.replace(/_/g, " ")} ${t}`;
  }
}
