"""Parse the uiautomator UI dump into a list of tappable screen targets.

This is the agent's "eyes". Unlike OCR, the node tree is the real view
hierarchy: every node already carries text / content-desc / class / bounds.
"""
import re
import xml.etree.ElementTree as ET
from pathlib import Path

_BOUNDS = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


def _center(bounds):
    m = _BOUNDS.search(bounds)
    if not m:
        return None
    x0, y0, x1, y1 = (int(v) for v in m.groups())
    return {
        "x": (x0 + x1) // 2,
        "y": (y0 + y1) // 2,
        "w": x1 - x0,
        "h": y1 - y0,
        "bounds": [x0, y0, x1, y1],
    }


def parse(path):
    """Parse a uiautomator dump XML file into a list of node dicts.

    Each dict: {text, desc, cls, pkg, res_id, x, y, w, h, bounds,
    clickable, scrollable, enabled, password, checked, selected, focused}
    Coordinates are device pixels, ready for tap().
    """
    tree = ET.parse(str(path))
    root = tree.getroot()
    out = []
    for node in root.iter("node"):
        b = node.get("bounds", "")
        c = _center(b)
        if not c:
            continue
        out.append({
            "text": node.get("text", "") or "",
            "desc": node.get("content-desc", "") or "",
            "cls": node.get("class", "") or "",
            "pkg": node.get("package", "") or "",
            "res_id": node.get("resource-id", "") or "",
            "x": c["x"], "y": c["y"], "w": c["w"], "h": c["h"],
            "bounds": c["bounds"],
            "clickable": node.get("clickable") == "true",
            "scrollable": node.get("scrollable") == "true",
            "enabled": node.get("enabled") != "false",
            "password": node.get("password") == "true",
            "checked": node.get("checked") == "true",
            "selected": node.get("selected") == "true",
            "focused": node.get("focused") == "true",
        })
    return out


def visible_text(nodes, min_len=1):
    """Return the label-ish tokens (text or content-desc) for quick printing."""
    toks = []
    for n in nodes:
        label = n["text"] or n["desc"]
        if label and len(label) >= min_len:
            toks.append(label)
    return toks
