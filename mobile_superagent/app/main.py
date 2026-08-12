"""FastAPI entrypoint for mobile_superagent.

Run:  uvicorn app.main:app --reload --port 8000
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from . import db
from .settings import settings
from .api import devices, tasks, routines, profile

app = FastAPI(title="mobile_superagent", version="0.1.0")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
    allow_headers=["*"])

app.include_router(devices.router)
app.include_router(tasks.router)
app.include_router(routines.router)
app.include_router(profile.router)


@app.on_event("startup")
def _startup():
    db.init_db()


@app.get("/health")
def health():
    return {"ok": True}


# static web (optional: templates served if present)
_web_static = Path(__file__).resolve().parent / "web" / "static"
if _web_static.exists():
    app.mount("/static", StaticFiles(directory=str(_web_static)),
              name="static")


@app.get("/")
def index():
    return {"service": "mobile_superagent",
            "docs": "/docs",
            "api": {"devices": "/api/devices", "tasks": "/api/tasks",
                    "routines": "/api/routines", "profile": "/api/profile"}}
