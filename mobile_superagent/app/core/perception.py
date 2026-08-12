"""Perception: capture the device state and turn it into a prompt-ready string.

Three senses:
  1. UI dump via uiautomator (exact element tree with tap-ready centers)
  2. Screenshot (persisted for replay + used by OCR + progress hashing)
  3. **OCR of the screenshot** — reads on-screen text (subtitles, titles) that
     the uiautomator dump misses (e.g. Douyin video titles live in the rendered
     video layer, not the view tree). This is the "video understanding" path:
     for FEED_SUMMARY we OCR each frame to read the video's title/caption.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from ..settings import settings


@dataclass
class CaptureState:
    foreground_package: str = ""
    activity: str = ""
    ui_dump: str = ""
    ui_nodes: list = None
    screenshot_path: str = ""
    screen_ocr: str = ""
    size: tuple | None = None
    locked: bool = False
    ime: str = ""
    target_installed: bool | None = None


def _tesseract_cmd() -> str:
    """Resolve the tesseract binary cross-platform: env override > shutil.which
    > the legacy Windows path (avoids hard-coding Windows in non-Windows CI)."""
    if settings.tesseract_cmd:
        return settings.tesseract_cmd
    found = shutil.which("tesseract")
    if found:
        return found
    legacy = "C:/Program Files/Tesseract-OCR/tesseract.exe"
    if Path(legacy).exists():
        return legacy
    return "tesseract"


def _ocr_image(path: str) -> str:
    """OCR the screenshot with Tesseract (chi_sim+eng). Returns visible text."""
    try:
        os.environ.setdefault("TESSDATA_PREFIX", settings.tessdata_dir)
        import pytesseract
        from PIL import Image
        pytesseract.pytesseract.tesseract_cmd = _tesseract_cmd()
        return pytesseract.image_to_string(
            Image.open(path), lang="chi_sim+eng").strip()
    except Exception:  # noqa: BLE001
        return ""


def capture_state(bridge, run_dir, step: int, ocr: bool = True,
                  target_package: str | None = None) -> CaptureState:
    """Capture current device state via the given bridge (the ADB adapter).

    bridge must expose: current_app(), screen_size(), dump_nodes(),
    screenshot(path) -> path. Optional: is_installed(), is_locked(),
    current_ime() for the heuristics below.

    `ocr` gates the expensive screenshot OCR pass. `target_package` (if given)
    is checked for installation so the model knows whether it must install it.
    """
    st = CaptureState()
    try:
        pkg, act = bridge.current_app()
        st.foreground_package = pkg or ""
        st.activity = act or ""
    except Exception:  # noqa: BLE001
        pass
    # lock screen / IME heuristics (cheap dumpsys; best-effort)
    try:
        st.locked = bridge.is_locked() if hasattr(bridge, "is_locked") else False
    except Exception:  # noqa: BLE001
        st.locked = False
    try:
        st.ime = bridge.current_ime() if hasattr(bridge, "current_ime") else ""
    except Exception:  # noqa: BLE001
        st.ime = ""
    if target_package and hasattr(bridge, "is_installed"):
        try:
            st.target_installed = bridge.is_installed(target_package)
        except Exception:  # noqa: BLE001
            st.target_installed = None
    try:
        st.size = bridge.screen_size()
    except Exception:  # noqa: BLE001
        st.size = None

    try:
        nodes = bridge.dump_nodes()
        st.ui_nodes = nodes
        texts = []
        for n in nodes:
            label = (n.get("text") or n.get("desc") or "").strip()
            if not label:
                continue
            x, y = n.get("x"), n.get("y")
            clickable = " (可点)" if n.get("clickable") else ""
            texts.append(f"{label}{clickable} @({x},{y})")
        st.ui_dump = "\n".join(texts[:60])
    except Exception:  # noqa: BLE001
        st.ui_dump = ""

    # screenshot + OCR
    try:
        spath = str(run_dir / f"step{step:02d}.png")
        path = bridge.screenshot(spath)
        st.screenshot_path = path or ""
    except Exception:  # noqa: BLE001
        st.screenshot_path = ""
    if st.screenshot_path and ocr:
        st.screen_ocr = _ocr_image(st.screenshot_path)
    return st


def state_to_prompt(st: CaptureState) -> str:
    lines = [
        "前台包名：%s" % (st.foreground_package or "unknown"),
        "当前activity：%s" % (st.activity or "unknown"),
        "屏幕尺寸：%s" % (list(st.size) if st.size else "unknown"),
    ]
    if st.locked:
        lines.append("⚠️ 设备处于锁屏状态，需先唤醒/解锁")
    if st.ime and "adbkeyboard" in st.ime.lower():
        lines.append("输入法：ADBKeyboard（支持中文输入 type_unicode）")
    if st.target_installed is not None:
        lines.append("目标App是否已安装：%s" % ("是" if st.target_installed else "否"))
    if st.screen_ocr:
        # OCR text is the "visual summary" — for video feeds this is the
        # actual on-screen title/subtitle.
        lines.append("\n[画面OCR（截图可见文字，视频标题/字幕在此）]")
        lines.append(st.screen_ocr[:800])
    lines.append("\n[UI元素树（点击目标用 @(x,y) 中心坐标）]")
    lines.append(st.ui_dump[:1200] or "(空)")
    return "\n".join(lines)
