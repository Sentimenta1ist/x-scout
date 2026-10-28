import asyncio
import threading
import webbrowser

import uvicorn
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import browser, db, pipeline
from .config import PORT, PROFILE_MD, ROOT

STATIC = ROOT / "x_scout" / "static"
app = FastAPI(title="x-scout")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
login_state = {"status": "unknown"}  # unknown | checking | waiting | ok | no
_tasks = set()


def _spawn(coro):
    t = asyncio.create_task(coro)
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


def _busy():
    if pipeline.state["running"] or login_state["status"] in ("checking", "waiting"):
        raise HTTPException(409, "busy: a run or login is in progress")


@app.on_event("startup")
async def startup():
    db.init()
    db.mark_stale_runs()
    _spawn(login_check())  # so the pill shows the real session state on open


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/state")
def get_state():
    return {**pipeline.state, "login": login_state["status"]}


@app.get("/api/settings")
def get_settings():
    return {**pipeline.load_settings(), "max_topics": pipeline.MAX_TOPICS}


@app.post("/api/settings")
def set_settings(s: dict = Body(...)):
    s.pop("max_topics", None)
    return pipeline.save_settings(s)


@app.get("/api/profile")
def get_profile():
    return {"text": pipeline.load_profile(), "custom": PROFILE_MD.exists()}


@app.post("/api/profile")
def set_profile(body: dict = Body(...)):
    PROFILE_MD.write_text(body.get("text", ""))
    return {"ok": True}


@app.post("/api/login")
async def login():
    _busy()

    async def go():
        login_state["status"] = "waiting"
        try:
            login_state["status"] = "ok" if await browser.interactive_login() else "no"
        except Exception:
            login_state["status"] = "no"

    _spawn(go())
    return {"ok": True}


@app.post("/api/login/check")
async def login_check():
    _busy()
    login_state["status"] = "checking"
    try:
        login_state["status"] = "ok" if await browser.check_login() else "no"
    except Exception:
        login_state["status"] = "no"
    return {"login": login_state["status"]}


@app.post("/api/run")
async def start_run():
    _busy()
    _spawn(pipeline.run(pipeline.load_settings()))
    return {"ok": True}


@app.post("/api/runs/{run_id}/reanalyze")
async def reanalyze(run_id: int):
    _busy()
    if not (r := db.get_run(run_id)) or not r.get("candidates"):
        raise HTTPException(404, "run has no stored candidates")
    _spawn(pipeline.reanalyze(run_id, pipeline.load_settings()))
    return {"ok": True}


@app.get("/api/runs")
def runs():
    return db.list_runs()


@app.get("/api/runs/{run_id}")
def run(run_id: int):
    r = db.get_run(run_id)
    if not r:
        raise HTTPException(404)
    r["has_candidates"] = bool(r.pop("candidates", None))
    return r


def main():
    url = f"http://127.0.0.1:{PORT}"
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print(f"x-scout on {url}  (Ctrl+C to stop)")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
