"""Pre-imported helpers for android-harness scripts.

The CLI injects every public name here into the exec namespace, so a script
can call tap_text(), dump_nodes(), open_app(), etc. directly. Agent-editable
helpers live in AGENT_WORKSPACE/agent_helpers.py and are merged on top.

Eyes = uiautomator node tree (real DOM). Hands = adb input.
"""
import hashlib
import importlib
import importlib.util
import os
import time
from pathlib import Path

from . import adb as _adb
from . import ui as _ui

# re-export the transport primitives so scripts can reach them
tap = _adb.tap
long_press = _adb.long_press
swipe = _adb.swipe
drag = _adb.drag
keyevent = _adb.keyevent
type_text = _adb.type_text
type_unicode = _adb.type_unicode
home = _adb.home
back = _adb.back
launch = _adb.launch
screen_size = _adb.screen_size
current_app = _adb.current_app
ensure_device = _adb.ensure_device
device_state = _adb.device_state
adbkeyboard_installed = _adb.adbkeyboard_installed
install_adbkeyboard = _adb.install_adbkeyboard

CORE_DIR = Path(__file__).resolve().parent
REPO_ROOT = CORE_DIR.parent.parent
AGENT_WORKSPACE = Path(
    os.environ.get("AGENT_WORKSPACE", REPO_ROOT / "agent-workspace"))


# --- reading the screen (eyes) -------------------------------------------

def dump_nodes():
    """Parse the current UI into node dicts (the element tree).

    Each node: {text, desc, cls, pkg, res_id, x, y, w, h, bounds,
    clickable, scrollable, ...}. Prefer this over screenshots — it's exact.
    """
    _adb.ensure_device()
    path = _adb.dump_ui()
    return _ui.parse(path)


def ocr():
    """iPhone-harness-compatible alias: visible text with tap-ready centers.

    Returns [{text, confidence:1.0, x, y, w, h}] for muscle-memory parity.
    """
    nodes = dump_nodes()
    return [{
        "text": n["text"] or n["desc"],
        "confidence": 1.0,
        "x": n["x"], "y": n["y"], "w": n["w"], "h": n["h"],
    } for n in nodes if (n["text"] or n["desc"])]


def find_text(query, exact=False, nodes=None):
    """Nodes whose text OR content-desc matches query (case-insensitive
    substring by default). Returns matching node dicts."""
    if nodes is None:
        nodes = dump_nodes()
    q = query.lower()
    hits = []
    for n in nodes:
        label = (n["text"] or n["desc"])
        if not label:
            continue
        if exact:
            if label.lower() == q:
                hits.append(n)
        elif q in label.lower():
            hits.append(n)
    return hits


def tap_text(query, index=0, exact=False, nodes=None):
    """Find a label on screen and tap its center. Raises with what IS visible
    on failure, so the next step is informed."""
    hits = find_text(query, exact=exact, nodes=nodes)
    if not hits:
        visible = _ui.visible_text(dump_nodes())[:30]
        raise RuntimeError(f"no visible text matches {query!r}; saw: {visible}")
    hit = hits[index]
    tap(hit["x"], hit["y"])
    return hit


def tap_res_id(res_id, index=0):
    """Tap by Android resource-id (more stable than label)."""
    nodes = dump_nodes()
    hits = [n for n in nodes if n["res_id"] == res_id]
    if not hits:
        raise RuntimeError(f"no node with resource-id {res_id!r}")
    hit = hits[index]
    tap(hit["x"], hit["y"])
    return hit


def screenshot(path=None):
    """Capture the screen to a PNG via screencap and return its path."""
    _adb.ensure_device()
    remote = "/sdcard/android-harness-shot.png"
    local = path or (Path(_adb._TMP) / "shot.png")
    _adb.run("shell", f"screencap -p {remote}", timeout=20)
    _adb.run("pull", remote, str(local), timeout=20)
    return str(local)


def screen_info():
    """{size, package, activity, nodes, texts} — handy snapshot of the screen.

    `package`/`activity` come from `adb shell dumpsys`; if that returns nothing
    on a given ROM, we fall back to the package seen in the uiautomator dump so
    the snapshot is still useful.
    """
    _adb.ensure_device()
    size = _adb.screen_size()
    pkg, act = _adb.current_app()
    nodes = dump_nodes()
    if not pkg and nodes:
        pkg = nodes[0].get("pkg")
    texts = [n.get("text") for n in nodes if n.get("text")]
    return {"size": size, "package": pkg, "activity": act,
            "state": _adb.device_state(), "nodes": len(nodes),
            "texts": texts}


# --- opening apps ---------------------------------------------------------

def open_app(name):
    """Open an app from the HOME screen by launcher icon label.

    Android has no global "open by name" without the package, so we go home,
    re-read the launcher, and tap the matching icon. If the label isn't on the
    current home page, swipe and retry (a couple of pages).
    """
    _adb.ensure_device()
    home()
    time.sleep(0.6)
    for attempt in range(4):  # home page + a few swipes
        hits = find_text(name)
        clickable = [h for h in hits if h["clickable"]]
        if clickable:
            tap(clickable[0]["x"], clickable[0]["y"])
            time.sleep(1.2)
            return clickable[0]
        # try next home page
        w, h = _adb.screen_size() or (1080, 2340)
        _adb.swipe(w // 2, int(h * 0.8), w // 2, int(h * 0.2), 0.2)
        time.sleep(0.6)
    raise RuntimeError(
        f"no launcher icon labeled {name!r} found on the home screen. "
        f"Use launch('com.example.pkg') with the package name instead.")


# --- scrolling through lists ---------------------------------------------
#
# End-of-list is decided by whether the SCREEN MOVED, never by whether the
# caller's parser found new items (mirrors phone-harness's proven design).

def _content_nodes():
    """Nodes in the scrollable middle area, excluding volatile status/nav
    strips (top 6% / bottom 8%)."""
    nodes = dump_nodes()
    h = (_adb.screen_size() or (1080, 2340))[1]
    top = h * 0.06
    bot = h * 0.92
    return [n for n in nodes
            if top < n["y"] < bot and (n["text"] or n["desc"])]


def _text_set(nodes):
    return frozenset((n["text"] or n["desc"]).strip()
                     for n in nodes if (n["text"] or n["desc"]).strip())


def _overlap(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def scroll_screen(direction="up", amount=0.6, settle=2.0, moved_thresh=0.6):
    """One scroll, then wait for the screen to settle so lazy-loaded content
    arrives before judging movement.

    Returns {moved, overlap, before, after, nodes}. `moved` is False when
    overlap >= moved_thresh (list didn't advance). 'up' reveals content below.
    """
    w, h = _adb.screen_size() or (1080, 2340)
    before = _text_set(_content_nodes())
    sign = {"up": -1, "down": 1}.get(direction)
    if sign is None:
        raise ValueError(f"direction must be 'up' or 'down', got {direction!r}")
    y0 = int(h * (0.3 if sign < 0 else 0.7))
    y1 = int(h * (0.3 + 0.4 * (1 if sign < 0 else -1)))
    _adb.swipe(w // 2, y0, w // 2, y1, 0.18)
    time.sleep(0.3)
    prev = None
    deadline = time.time() + settle
    while time.time() < deadline:
        boxes = _content_nodes()
        cur = _text_set(boxes)
        if cur == prev:
            break
        prev = cur
        time.sleep(0.3)
    after = prev or frozenset()
    return {"moved": _overlap(before, after) < moved_thresh,
            "overlap": round(_overlap(before, after), 3),
            "before": before, "after": after, "nodes": _content_nodes()}


def scroll_until(done, direction="up", amount=0.6, max_scrolls=60, settle=2.0):
    """Scroll until done(nodes) is truthy or the list stops moving."""
    nodes = _content_nodes()
    hit = done(nodes)
    if hit:
        return hit
    stale = 0
    for _ in range(max_scrolls):
        res = scroll_screen(direction, amount, settle)
        hit = done(res["nodes"])
        if hit:
            return hit
        if res["moved"]:
            stale = 0
        else:
            stale += 1
            if stale >= 2:
                return None
            time.sleep(0.5)
    return None


def scroll_collect(extract=None, key=None, direction="up", amount=0.6,
                   max_scrolls=400, end_after=3, settle=2.0, on_progress=None):
    """Scroll a list top-to-bottom, extracting + de-duping items each screen,
    until the list reaches its true end.

    Returns {items, stop, scrolls}. stop is 'reached-end' or 'max-scrolls'.
    """
    extract = extract or (lambda nodes: [ (n["text"] or n["desc"]).strip()
                                          for n in nodes
                                          if (n["text"] or n["desc"]).strip()])
    key = key or (lambda x: x)
    seen, order = set(), []

    def ingest(nodes):
        new = 0
        for item in extract(nodes):
            k = key(item)
            if k in seen:
                continue
            seen.add(k)
            order.append(item)
            new += 1
        return new

    ingest(_content_nodes())
    stale = 0
    for i in range(1, max_scrolls + 1):
        res = scroll_screen(direction, amount, settle)
        new = ingest(res["nodes"])
        if on_progress:
            on_progress(i, len(order), new, res["moved"], res["overlap"])
        if res["moved"]:
            stale = 0
        else:
            stale += 1
            if stale >= end_after:
                return {"items": order, "stop": "reached-end", "scrolls": i}
            time.sleep(0.5)
    return {"items": order, "stop": "max-scrolls", "scrolls": max_scrolls}


# --- timing ---------------------------------------------------------------

def wait(seconds=1.0):
    time.sleep(seconds)


def wait_stable(timeout=6.0, interval=0.5, settle=2):
    """Wait until `settle` consecutive dumps are identical (animation done)."""
    prev, same = None, 0
    deadline = time.time() + timeout
    while time.time() < deadline:
        path = _adb.dump_ui()
        digest = hashlib.md5(Path(path).read_bytes()).hexdigest()
        same = same + 1 if digest == prev else 0
        if same >= settle - 1:
            return True
        prev = digest
        time.sleep(interval)
    return False


def _load_agent_helpers():
    p = AGENT_WORKSPACE / "agent_helpers.py"
    if not p.exists():
        return
    spec = importlib.util.spec_from_file_location("android_harness_agent_helpers", p)
    if not spec or not spec.loader:
        return
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name, value in vars(module).items():
        if not name.startswith("_"):
            globals()[name] = value


_load_agent_helpers()

# Task-level helpers are imported last to avoid a circular import:
# task.py depends on helpers, so helpers must be fully defined first.
from . import task as _task

# re-export task-level helpers so scripts can build/run tasks directly
run_task = _task.run_task
step_open = _task.step_open
step_tap = _task.step_tap
step_tap_id = _task.step_tap_id
step_type = _task.step_type
step_type_unicode = _task.step_type_unicode
step_wait = _task.step_wait
step_ask = _task.step_ask
plan_from_goal = _task.plan_from_goal
