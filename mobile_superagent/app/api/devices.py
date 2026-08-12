"""Device API: list, refresh scan, live state."""
from fastapi import APIRouter

from .. import db
from ..core.device_manager import DeviceManager

router = APIRouter(prefix="/api/devices", tags=["devices"])
_dm = DeviceManager()


@router.get("")
def list_devices():
    return db.list_devices()


@router.post("/refresh")
def refresh():
    return _dm.refresh()


@router.get("/{device_id}/state")
def device_state(device_id: str):
    dev = db.get_device(device_id)
    if not dev:
        return {"error": "device not found"}
    bridge = _dm.get(dev["serial"])
    pkg, act = bridge.current_app()
    return {"device_id": device_id, "serial": dev["serial"],
            "foreground_package": pkg, "activity": act,
            "status": dev["status"]}
