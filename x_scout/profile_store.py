"""data/profiles/<handle>/: scrapes/<id>.json (+ .responses.json.gz), analyses/<id>.json, snapshots.jsonl."""
import gzip
import json
import re
from datetime import datetime, timezone

from . import config

_HANDLE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
_ID = re.compile(r"^\d{8}-\d{6}$")
_URL_HANDLE = re.compile(r"(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})", re.IGNORECASE)


def clean_handle(raw):
    """'@Name', 'name' or a profile URL → 'Name'. Raises ValueError otherwise: the value ends up in URLs and paths."""
    s = (raw or "").strip()
    if m := _URL_HANDLE.search(s):
        s = m.group(1)
    s = s.lstrip("@")
    if not _HANDLE.match(s):
        raise ValueError(f"not an X handle: {raw!r}")
    return s


def _dir(handle):
    return config.PROFILES / clean_handle(handle).lower()


def new_id():
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _check_id(id_):
    if not _ID.match(id_ or ""):
        raise ValueError(f"bad id: {id_!r}")
    return id_


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False))
    tmp.replace(path)


def save_scrape(handle, scrape_id, scrape, responses=None):
    _write(_dir(handle) / "scrapes" / f"{_check_id(scrape_id)}.json", scrape)
    if responses:  # raw X JSON: lets a parser fix be re-applied without touching X again
        with gzip.open(_dir(handle) / "scrapes" / f"{scrape_id}.responses.json.gz", "wt") as f:
            json.dump(responses, f)


def load_scrape(handle, scrape_id):
    return json.loads((_dir(handle) / "scrapes" / f"{_check_id(scrape_id)}.json").read_text())


def save_analysis(handle, analysis):
    _write(_dir(handle) / "analyses" / f"{_check_id(analysis['id'])}.json", analysis)


def load_analysis(handle, analysis_id):
    return json.loads((_dir(handle) / "analyses" / f"{_check_id(analysis_id)}.json").read_text())


def add_snapshot(handle, snap):
    d = _dir(handle)
    d.mkdir(parents=True, exist_ok=True)
    with (d / "snapshots.jsonl").open("a") as f:
        f.write(json.dumps(snap) + "\n")


def snapshots(handle):
    path = _dir(handle) / "snapshots.jsonl"
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()] if path.exists() else []


def history():
    """Analyzed accounts, most recently analyzed first, with their analyses newest first."""
    out = []
    if not config.PROFILES.exists():
        return out
    for d in config.PROFILES.iterdir():
        items = []
        for f in sorted((d / "analyses").glob("*.json"), reverse=True) if (d / "analyses").exists() else []:
            try:
                a = json.loads(f.read_text())
            except json.JSONDecodeError:
                continue
            items.append({k: a.get(k) for k in ("id", "scrape_id", "created_at", "status")} | {
                "posts": len(a.get("posts") or []), "has_report": bool(a.get("report"))})
        if items:
            a = load_analysis(d.name, items[0]["id"])
            out.append({"handle": a["profile"]["handle"], "name": a["profile"]["name"], "analyses": items,
                        "snapshots": len(snapshots(d.name))})
    return sorted(out, key=lambda h: h["analyses"][0]["id"], reverse=True)
