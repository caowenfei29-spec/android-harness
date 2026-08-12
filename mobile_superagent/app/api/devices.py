"""Device API: list, refresh scan, live state + preview screenshot."""
from fastapi import APIRouter
from fastapi.responses import FileResponse
from pathlib import Path
from pydantic import BaseModel

from .. import db
from ..settings import settings
from ..core.device_manager import DeviceManager

router = APIRouter(prefix="/api/devices", tags=["devices"])
_dm = DeviceManager()


class WifiConnectReq(BaseModel):
    host: str
    port: int = 5555


@router.get("")
def list_devices():
    return db.list_devices()


@router.post("/refresh")
def refresh():
    return _dm.refresh()


@router.post("/connect_wifi")
def connect_wifi(req: WifiConnectReq):
    return _dm.connect_wifi(req.host, req.port)


@router.get("/{device_id}/screenshot")
def device_screenshot(device_id: str):
    """Live screenshot of a device (for the Devices preview panel)."""
    dev = db.get_device(device_id)
    if not dev:
        return {"error": "device not found"}
    bridge = _dm.get(dev["serial"])
    p = Path(settings.storage_dir) / "preview" / f"{device_id}.png"
    p.parent.mkdir(parents=True, exist_ok=True)
    path = bridge.screenshot(str(p))
    if path and Path(path).exists():
        return FileResponse(str(path), media_type="image/png")
    return {"error": "screenshot failed"}


@router.get("/{device_id}/state")
def device_state(device_id: str):
    dev = db.get_device(device_id)
    if not dev:
        return {"error": "device not found"}
    bridge = _dm.get(dev["serial"])
    pkg, act = bridge.current_app()
    return {"device_id": device_id, "serial": dev["serial"],
            "foreground_package": pkg, "foreground_activity": act,
            "activity": act,
            "status": dev["status"],
            "screenshot_url": f"/api/devices/{device_id}/screenshot"}
