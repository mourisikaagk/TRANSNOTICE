from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Mapping

from timeutil import format_local

TRACKED_FIELDS = (
    "title", "notice_type", "summary", "area", "routes",
    "source_url", "published_at", "valid_from", "valid_to", "withdrawn",
)
LABELS = {
    "title": "Title", "notice_type": "Type", "summary": "Summary", "area": "Affected area",
    "source_url": "Source link", "published_at": "Published time", "valid_from": "Start time",
}


@dataclass
class FieldChange:
    field: str
    kind: str
    old: object
    new: object
    description: str

    def as_dict(self) -> dict:
        return asdict(self)


def canonical_content(content: Mapping) -> dict:
    result: dict = {}
    for name in TRACKED_FIELDS:
        value = content.get(name)
        if name == "routes":
            value = sorted(set(value or []))
        elif name == "withdrawn":
            value = bool(value)
        elif isinstance(value, str):
            value = " ".join(value.split()) or None
        result[name] = value
    return result


def content_hash(content: Mapping) -> str:
    payload = json.dumps(canonical_content(content), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def diff_content(old: Mapping, new: Mapping, tz_name: str) -> list[FieldChange]:
    old, new = canonical_content(old), canonical_content(new)
    changes: list[FieldChange] = []

    if old["withdrawn"] != new["withdrawn"]:
        kind = "withdrawn" if new["withdrawn"] else "reinstated"
        text = "Notice withdrawn by the source." if new["withdrawn"] else "Notice reinstated by the source."
        changes.append(FieldChange("withdrawn", kind, old["withdrawn"], new["withdrawn"], text))

    if old["valid_to"] != new["valid_to"]:
        changes.append(_end_time_change(old["valid_to"], new["valid_to"], tz_name))

    if old["routes"] != new["routes"]:
        added = sorted(set(new["routes"]) - set(old["routes"]))
        removed = sorted(set(old["routes"]) - set(new["routes"]))
        parts = []
        if added:
            parts.append("added " + ", ".join(added))
        if removed:
            parts.append("removed " + ", ".join(removed))
        changes.append(FieldChange("routes", "routes_changed", old["routes"], new["routes"],
                                   "Affected routes: " + "; ".join(parts) + "."))

    for name in ("title", "notice_type", "summary", "area", "source_url", "published_at", "valid_from"):
        if old[name] == new[name]:
            continue
        label = LABELS[name]
        if name in ("published_at", "valid_from"):
            before, after = format_local(old[name], tz_name) or "not set", format_local(new[name], tz_name) or "not set"
            text = f"{label} changed from {before} to {after}."
        elif name == "summary":
            text = "Summary text was revised."
        else:
            text = f"{label} changed from '{old[name] or 'not set'}' to '{new[name] or 'not set'}'."
        changes.append(FieldChange(name, "revised", old[name], new[name], text))
    return changes


def _end_time_change(old: str | None, new: str | None, tz_name: str) -> FieldChange:
    if old is None:
        text = f"End time announced: {format_local(new, tz_name)}."
        return FieldChange("valid_to", "end_set", old, new, text)
    if new is None:
        text = f"End time removed; the notice is now open-ended (was {format_local(old, tz_name)})."
        return FieldChange("valid_to", "extended", old, new, text)
    kind = "extended" if new > old else "shortened"
    verb = "extended" if kind == "extended" else "shortened"
    text = f"Validity {verb}: end time moved from {format_local(old, tz_name)} to {format_local(new, tz_name)}."
    return FieldChange("valid_to", kind, old, new, text)


def classify_changes(changes: list[FieldChange]) -> str:
    kinds = {c.kind for c in changes}
    for kind in ("withdrawn", "reinstated", "extended", "shortened", "routes_changed"):
        if kind in kinds:
            return kind
    return "revised"


def summarize_changes(changes: list[FieldChange]) -> str:
    return " ".join(c.description for c in changes) if changes else "No field changes."
