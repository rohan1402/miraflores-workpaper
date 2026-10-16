"""Sensitive data never leaves the server unmasked, except through the logged unmask (D11).

The leak is not only the extracted values: printed pages carry full SSNs (every W-2,
last year's return, the Social Security card), the Swedish account number, the IP PIN.
So masking runs on the way out, over every string in every response:

  - values the packet itself marks as sensitive: value_type ssn or account_number, any
    field named like a PIN, the household's SSNs, IP PINs and bank numbers, the e-file
    signature PINs in the timeline. Each is replaced wherever it appears, including pages.
  - anything SSN-shaped (123-45-6789), so a number typed into a note is masked too.

Masked forms keep what a reviewer needs to tell values apart: the last four digits of an
SSN or account, nothing of a PIN.
"""

from __future__ import annotations

import re

from .packet import Packet

SSN_SHAPED = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
SIGNATURE_PIN = re.compile(r"\bPIN (\d{5})\b")
SENSITIVE_TYPES = {"ssn", "account_number"}


def mask_ssn(ssn: str) -> str:
    return f"***-**-{ssn[-4:]}"


def mask_account(number: str) -> str:
    digits = re.sub(r"\D", "", number)
    return f"****{digits[-4:]}"


def mask_pin(_: str) -> str:
    return "******"


class Masker:
    """Built once from the packet. Call it on any JSON-able object to get a masked copy."""

    def __init__(self, packet: Packet):
        self.secrets: dict[str, str] = {}   # clear text -> masked text
        for ev in packet.raw["extracted_values"]:
            if ev["value"] is None:
                continue
            if ev["value_type"] == "ssn":
                self._add(str(ev["value"]), mask_ssn)
            elif ev["value_type"] == "account_number":
                self._add(str(ev["value"]), mask_account)
            elif "pin" in ev["field"].lower():
                self._add(str(ev["value"]), mask_pin)
        household = packet.raw["household"]
        for person in household["people"]:
            if person.get("ssn"):
                self._add(person["ssn"], mask_ssn)
            if person.get("ip_pin"):
                self._add(person["ip_pin"], mask_pin)
        bank = household.get("bank_account_for_refund_or_payment") or {}
        for key in ("routing", "account"):
            if bank.get(key):
                self._add(bank[key], mask_account)
        for event in packet.raw["timeline"]:
            for pin in SIGNATURE_PIN.findall(str(event.get("detail") or "")):
                self._add(pin, mask_pin)
        # One pattern, longest secret first, never matching inside a longer run of digits
        # (so the PIN 41207 is not replaced inside 1412078).
        ordered = sorted(self.secrets, key=len, reverse=True)
        self._pattern = re.compile("|".join(rf"(?<!\d){re.escape(c)}(?!\d)" for c in ordered)) if ordered else None

    def _add(self, clear: str, how) -> None:
        if clear and len(clear) >= 4:
            self.secrets[clear] = how(clear)

    def text(self, s: str) -> str:
        if self._pattern is not None:
            s = self._pattern.sub(lambda m: self.secrets[m.group(0)], s)
        return SSN_SHAPED.sub(lambda m: mask_ssn(m.group(0)), s)

    def __call__(self, obj):
        if isinstance(obj, str):
            return self.text(obj)
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                if isinstance(k, str) and k.lower().startswith("ssn") and isinstance(v, str):
                    out[k] = mask_ssn(v) if v else v
                elif isinstance(obj.get("value_type"), str) and obj["value_type"] in SENSITIVE_TYPES \
                        and k in ("value", "text_as_read") and v:
                    out[k] = self.text(str(v)) if str(v) in self.secrets else mask_account(str(v))
                else:
                    out[k] = self(v)
            return out
        if isinstance(obj, (list, tuple)):
            return [self(v) for v in obj]
        return obj


def reveal(packet: Packet, ref: str):
    """The clear value behind a reference, for the logged unmask. None if there is nothing sensitive there."""
    if ref.startswith("ev-"):
        ev = packet.values.get(ref)
        return ev["value"] if ev else None
    if ref.startswith("household:"):
        person_id, _, field = ref[len("household:"):].partition(".")
        person = next((p for p in packet.raw["household"]["people"] if p["id"] == person_id), None)
        return person.get(field or "ssn") if person else None
    if ref.startswith("doc:") and "#page" in ref:
        doc_id, _, page = ref[len("doc:"):].partition("#page")
        return (packet.page_text(doc_id, int(page)) or None) if page.isascii() and page.isdigit() else None
    if ref == "household.bank_account":
        return packet.raw["household"].get("bank_account_for_refund_or_payment")
    return None
