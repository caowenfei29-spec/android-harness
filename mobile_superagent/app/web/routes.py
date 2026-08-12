"""Web console routes: Jinja2 pages for the control console."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["web"])

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(request, "index.html",
                                       {"title": "控制台", "active": "home"})


@router.get("/tasks/{task_id}", response_class=HTMLResponse)
async def task_detail(request: Request, task_id: str):
    return templates.TemplateResponse(request, "task_detail.html",
                                       {"title": f"任务 {task_id}",
                                        "active": "home",
                                        "task_id": task_id})


@router.get("/routines", response_class=HTMLResponse)
async def routines_page(request: Request):
    return templates.TemplateResponse(request, "routines.html",
                                       {"title": "定时任务",
                                        "active": "routines"})


@router.get("/devices", response_class=HTMLResponse)
async def devices_page(request: Request):
    return templates.TemplateResponse(request, "devices.html",
                                       {"title": "设备", "active": "devices"})
