"""FastAPI entrypoint for mobile_superagent.

Run:  uvicorn app.main:app --reload --port 8000
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from . import db
from .web.routes import router as web_router
from .api import devices, tasks, routines, profile


class NoCacheStaticFiles(StaticFiles):
    """Serve static assets with no-cache headers so dev edits show immediately."""
    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        if resp.status_code < 400:
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return resp


app = FastAPI(title="Mobile Superagent", version="0.1.0")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
    allow_headers=["*"])

# static assets (css/js)
_web_static = Path(__file__).resolve().parent / "web" / "static"
app.mount("/static", NoCacheStaticFiles(directory=str(_web_static)),
          name="static")

# web console pages
app.include_router(web_router)

# api
app.include_router(devices.router)
app.include_router(tasks.router)
app.include_router(routines.router)
app.include_router(profile.router)


@app.on_event("startup")
def _startup():
    db.init_db()
    _start_scheduler()


def _start_scheduler():
    """Launch the routines scheduler in a background daemon thread."""
    import threading
    from .scheduler.routines_scheduler import scheduler_loop
    t = threading.Thread(target=scheduler_loop, daemon=True,
                         name="routines-scheduler")
    t.start()


@app.get("/health")
def health():
    return {"ok": True}
