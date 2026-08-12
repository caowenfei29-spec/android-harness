"""Device manager: discover connected phones and hand out bridge clients."""
from __future__ import annotations

from .device_bridge import ADB, AndroidDevice
from .. import db


class DeviceManager:
    def __init__(self):
        self.clients: dict[str, AndroidDevice] = {}

    def list_serials(self) -> list[str]:
        # adb devices -l -> parse serials
        try:
            out = ADB.run("devices", timeout=10, check=False).stdout
            serials = []
            for line in out.splitlines()[1:]:
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                if len(parts) >= 2 and parts[1] == "device":
                    serials.append(parts[0])
            return serials
        except Exception:  # noqa: BLE001
            return []

    def refresh(self) -> list[dict]:
        """Scan adb devices, upsert into DB, return device records."""
        records = []
        for serial in self.list_serials():
            dev = self.get(serial)
            props = {}
            try:
                size = dev.screen_size()
                props["screen"] = "%dx%d" % size if size else None
                out = ADB.run("shell", "getprop", "ro.product.model",
                              timeout=10, check=False).stdout
                props["model"] = out.strip()
                out2 = ADB.run("shell", "getprop", "ro.build.version.release",
                               timeout=10, check=False).stdout
                props["android_version"] = out2.strip()
            except Exception:  # noqa: BLE001
                pass
            # WiFi adb devices have a "ip:port" serial; USB serials do not.
            connect_type = "wifi" if ":" in serial else "usb"
            rid = db.upsert_device(serial, name=props.get("model", serial),
                                   connect_type=connect_type, props=props)
            rec = db.get_device(rid)
            records.append(rec)
        return records

    def connect_wifi(self, host: str, port: int = 5555) -> dict:
        """`adb connect ip:port` to attach a WiFi device, then refresh."""
        target = f"{host}:{port}"
        try:
            out = ADB.run("connect", target, timeout=15, check=False).stdout
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}
        self.refresh()
        return {"ok": True, "output": out.strip()}

    def get(self, serial: str) -> AndroidDevice:
        dev = self.clients.get(serial)
        if dev is None:
            dev = AndroidDevice(serial)
            self.clients[serial] = dev
        return dev

    def ensure_online(self, serial: str, retries: int = 3) -> AndroidDevice:
        import time
        last_err = None
        for _ in range(retries):
            try:
                if serial not in self.list_serials():
                    time.sleep(1)
                    continue
                dev = self.get(serial)
                # light liveness probe
                _ = dev.current_app()
                return dev
            except Exception as e:  # noqa: BLE001
                last_err = e
                self.clients.pop(serial, None)
                time.sleep(1)
        raise RuntimeError(f"设备不可用: {serial}, err={last_err}")
