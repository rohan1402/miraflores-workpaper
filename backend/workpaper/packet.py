"""Layer 1: the packet, loaded as delivered and never edited.

The packet is pipeline output. `printed_content` on each page is the truth;
`extracted_values` are what the pipeline read (can be wrong); `return_versions`
are what the engine computed (can also be wrong). Nothing in this module changes
the packet. It only builds lookup tables over it.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKET_PATH = REPO_ROOT / "data" / "okafor_lindqvist_2025_packet.json"


class Packet:
    """Read-only view of the packet plus indexes. Treat every attribute as frozen."""

    def __init__(self, raw: dict, sha256: str):
        self.raw = raw
        self.sha256 = sha256  # proves the file was loaded as delivered
        self.tax_year: int = raw["household"]["tax_year"]

        self.documents: dict[str, dict] = {d["id"]: d for d in raw["documents"]}
        self.pages: dict[tuple[str, int], str] = {
            (d["id"], p["page"]): p["printed_content"] for d in raw["documents"] for p in d["pages"]
        }

        self.values: dict[str, dict] = {e["id"]: e for e in raw["extracted_values"]}
        self.values_by_doc: dict[str, list[dict]] = defaultdict(list)
        for e in raw["extracted_values"]:
            self.values_by_doc[e["document_id"]].append(e)

        # Return versions in time order (v1, v2, v3).
        self.versions: list[dict] = sorted(raw["return_versions"], key=lambda v: v["computed_at"])
        self.version_by_id: dict[str, dict] = {v["version"]: v for v in self.versions}
        self.lines: dict[str, dict[str, dict]] = {
            v["version"]: {line["key"]: line for line in v["lines"]} for v in self.versions
        }

        client = raw["client"]
        self.client_items: dict[str, dict] = {}
        for q in client["questionnaire"]:
            self.client_items[q["id"]] = {"kind": "questionnaire", "at": q["answered_at"], **q}
        for m in client["messages"]:
            self.client_items[m["id"]] = {"kind": "message", "at": m["sent_at"], **m}
        for c in client["call_notes"]:
            self.client_items[c["id"]] = {"kind": "call_note", "at": c["date"], **c}

        self.people: dict[str, dict] = {p["id"]: p for p in raw["household"]["people"]}
        self.staff: dict[str, dict] = {s["id"]: s for s in raw["firm"]["staff"]}
        self.client_users: dict[str, dict] = {c["id"]: c for c in raw["firm"]["client_users"]}

    # ---- pages and documents -------------------------------------------------

    def page_text(self, doc_id: str, page: int) -> str:
        return self.pages.get((doc_id, page), "")

    def document_text(self, doc_id: str) -> str:
        doc = self.documents[doc_id]
        return "\n".join(p["printed_content"] for p in doc["pages"])

    # ---- versions ------------------------------------------------------------

    def version_at(self, as_of: str | None) -> dict:
        """The latest return version computed at or before `as_of` (None = latest).

        Before v1 exists there is no return yet; we still return v1 so callers
        always have lines to show, and the projection records the real clock.
        """
        if as_of is None:
            return self.versions[-1]
        current = self.versions[0]
        for v in self.versions:
            if v["computed_at"] <= as_of:
                current = v
        return current

    def previous_version(self, version_id: str) -> dict | None:
        ids = [v["version"] for v in self.versions]
        i = ids.index(version_id)
        return self.versions[i - 1] if i > 0 else None

    # ---- references ----------------------------------------------------------

    def resolve(self, ref: str):
        """Return the object a reference points at (see readme.reference_formats)."""
        kind = ref_kind(ref)
        if kind == "value":
            return self.values.get(ref)
        if kind == "document":
            return self.documents.get(ref)
        if kind == "page":
            doc_id, page = parse_page_ref(ref)
            return {"document_id": doc_id, "page": page, "printed_content": self.page_text(doc_id, page)}
        if kind == "client":
            return self.client_items.get(ref)
        if kind == "prior_year":
            return json_pointer(self.raw["prior_years"], ref[len("py:"):])
        if kind == "agency":
            return json_pointer(self.raw["tax_agency_records"], ref[len("agency:"):])
        if kind == "param":
            return self.raw["engine_reference"]["parameters"].get(ref[len("ref:param."):])
        if kind == "fx":
            currency, _, rate = ref[len("ref:fx."):].partition(".")
            return self.raw["engine_reference"]["parameters"]["fx"].get(currency, {}).get(rate)
        if kind == "person":
            return self.people.get(ref[len("household:"):])
        if kind == "line":
            return self.lines[self.versions[-1]["version"]].get(ref[len("line:"):])
        return None


def ref_kind(ref: str) -> str:
    """Classify a reference string. Packet formats plus a few of our own (line:, area:, event:, finding:)."""
    if ref.startswith("ev-"):
        return "value"
    if ref.startswith("doc:") and "#page" in ref:
        return "page"
    if len(ref) == 3 and ref[0] == "D" and ref[1:].isdigit():
        return "document"
    if ref.startswith(("qa-", "msg-", "call-")):
        return "client"
    if ref.startswith("py:"):
        return "prior_year"
    if ref.startswith("agency:"):
        return "agency"
    if ref.startswith("ref:param."):
        return "param"
    if ref.startswith("ref:fx."):
        return "fx"
    if ref.startswith("household:"):
        return "person"
    if ref.startswith("asset:"):
        return "asset"
    if ref.startswith("timeline:"):
        return "timeline"
    if ref.startswith("line:"):
        return "line"
    if ref.startswith("area:"):
        return "area"
    if ref.startswith("event:"):
        return "event"
    if ref.startswith("finding:"):
        return "finding"
    if ref == "return":
        return "return"
    if ref.startswith("notice:"):
        return "notice"
    if ref.startswith("time:"):
        return "time"
    if ref.startswith("plan:"):
        return "plan"
    return "unknown"


def parse_page_ref(ref: str) -> tuple[str, int]:
    """'doc:D31#page32' -> ('D31', 32)."""
    doc_part, _, page_part = ref[len("doc:"):].partition("#page")
    return doc_part, int(page_part)


def page_ref(doc_id: str, page: int) -> str:
    return f"doc:{doc_id}#page{page}"


def json_pointer(root, pointer: str):
    """Resolve an RFC 6901 JSON Pointer such as '/carryovers_into_2025/capital_loss_short'."""
    node = root
    for raw_part in pointer.lstrip("/").split("/"):
        if raw_part == "":
            continue
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(node, list):
            node = node[int(part)]
        else:
            node = node[part]
    return node


def load_packet(path: Path | str = PACKET_PATH) -> Packet:
    data = Path(path).read_bytes()
    return Packet(json.loads(data), hashlib.sha256(data).hexdigest())
