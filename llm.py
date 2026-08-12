#!/usr/bin/env python3
"""Local LLM bridge for android-harness (natural-language control + summaries).

Reads credentials from a local .env file ONLY. The key never leaves this
process and is never printed, logged in cleartext, or sent anywhere except the
configured LLM endpoint.

Supported providers (OpenAI-compatible): DeepSeek, OpenAI, OpenClaw/local, etc.
Set in .env:
    LLM_BASE_URL=https://api.deepseek.com/v1
    LLM_API_KEY=sk-...
    LLM_MODEL=deepseek-chat
    LLM_TIMEOUT=60

Safety: translate() is constrained to a whitelist of read-only / navigation
calls. Any outward action (send, post, buy, delete, install, uninstall, change
settings) MUST be expressed as a `step_ask(...)` so run_task stops for the
human. The translator is told never to emit raw outward calls.
"""
import json
import os
import urllib.request
import urllib.error
from pathlib import Path

_HARNESS_ROOT = Path(__file__).resolve().parent


def _load_env():
    env_path = _HARNESS_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()

BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1")
API_KEY = os.environ.get("LLM_API_KEY", "")
MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")
TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "60"))


def configured() -> bool:
    """True if an API key + base url are present."""
    return bool(API_KEY and BASE_URL)


def _chat(system: str, user: str) -> str:
    if not configured():
        raise RuntimeError(
            "LLM 未配置：请在 android-harness/.env 里设置 LLM_BASE_URL / "
            "LLM_API_KEY / LLM_MODEL（key 只存本地，不外泄）"
        )
    body = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
    }).encode("utf-8")
    req = urllib.request.Request(
        BASE_URL.rstrip("/") + "/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + API_KEY,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"LLM HTTP {e.code}: {detail}")
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"LLM 调用失败: {e}")


# ---------------------------------------------------------------------------
# Natural-language -> harness call (constrained)
# ---------------------------------------------------------------------------

_TRANS_SYSTEM = """你把一个中文手机操作指令翻译成一段 Python 代码，只能在 android_harness 的
helpers / task 命名空间里调用。可用的安全原语：

  from android_harness import helpers as H, task
  H.launch("包名或应用名")        # 打开应用
  H.tap_text("文字")              # 按文字点击
  H.tap_res_id("res_id")
  H.scroll_screen(direction="up", amount=0.6)   # 上滑（刷视频/翻页）
  H.dump_nodes()                  # 返回当前屏所有可交互节点(list[dict])
  H.screen_info()                 # 返回 {size,package,activity,texts,...}
  task.run_task([step, ...])      # 任务循环，遇到 step_ask 停止
  task.step_open/app/tap/tap_id/type/type_unicode/wait/ask(...)

严格规则（违反即危险）：
1. 只输出"读取/导航"操作：打开、点击、上滑、读屏。不要输出任何会修改手机、
   对外发送、花钱、删除的步骤。
2. 任何"发送消息/发帖/购买/删除/卸载/安装/修改设置/关注/点赞"等外向动作，
   都必须写成 task.step_ask("请确认：<具体动作>") 让真人确认，绝不能直接执行。
3. 输出**只有 Python 代码**，不要解释、不要 markdown 代码块围栏。
4. 若指令本身含糊或有外向风险，输出一行注释 # NEEDS_CONFIRM: <说明> 然后停止。
5. 包名不知道时，用 H.launch("应用中文名") 让 harness 尝试按名打开。

示例——指令"打开抖音并上滑刷5个视频，每屏读出标题"：
  from android_harness import helpers as H, task
  H.launch("抖音")
  for _ in range(5):
      H.scroll_screen(direction="up", amount=0.7)
      import time; time.sleep(2)
      nodes = H.dump_nodes()
      titles = [n.get("text") for n in nodes if n.get("text")]
      print("SCREEN_TITLES:", titles)
"""


def translate(prompt: str) -> str:
    """Translate a Chinese instruction into harness Python code (string)."""
    code = _chat(_TRANS_SYSTEM, prompt).strip()
    # strip accidental markdown fences
    if code.startswith("```"):
        code = code.split("```", 2)[1]
        if code.startswith("python"):
            code = code[len("python"):]
    return code.strip()


# ---------------------------------------------------------------------------
# Summarise captured screen text
# ---------------------------------------------------------------------------

_SUMMARY_SYSTEM = """你是手机屏幕内容的总结助手。用户会给你若干屏抓取的文字（标题、作者、
点赞、评论等）。请用简洁中文总结：刷了哪些内容、主题分布、是否有广告/推荐倾向、
值得注意的信息。只基于给出的文字，不要编造没出现的内容。输出 3-6 条要点。"""


def summarize(screens: list) -> str:
    """screens: list of strings (one per captured screen). Returns a summary."""
    joined = "\n\n".join(
        f"[第{i+1}屏]\n{t}" for i, t in enumerate(screens)
    )
    return _chat(_SUMMARY_SYSTEM, joined).strip()


# ---------------------------------------------------------------------------
# Natural-language -> structured PLAN (Airtap-style step flow)
# ---------------------------------------------------------------------------

_PLAN_SYSTEM = """你是一个手机操作规划器。用户会给一个中文指令（可能是模糊的口语目标），
你要先理解意图，然后把它拆成一串**有名字、可逐步执行**的步骤，输出为严格的 JSON。

你能调用的手机原语（每个步骤的 code 字段只能调用这些，且只用读取/导航/打开/点击/上滑/等待）：

  H.open_app("应用中文名")        # 打开应用【中文名时用这个】——回桌面点图标，靠桌面标签匹配
  H.launch("包名")                # 打开应用【知道包名时用这个，最可靠】——如 "com.tencent.mm"
  H.tap_text("屏幕上的文字")          # 按文字点击
  H.tap_res_id("resource-id")        # 按 id 点击
  H.scroll_screen(direction="up")    # 上滑（刷视频/翻页）
  H.dump_nodes()                     # 读当前屏所有可交互节点（list[dict]）
  H.screen_info()                    # 读屏幕/应用状态（dict）
  time.sleep(秒)                     # 等待加载

打开应用的规则：
- 如果你能确定包名（如 com.tencent.mm=微信、com.ss.android.ugc.aweme=抖音、com.android.vending=Play商店），
  优先用 H.launch("包名")，最可靠。
- 不确定包名时，用 H.open_app("应用中文名") 回桌面点图标。

严格规则：
1. **只有只读/导航动作**能放进 code：打开、点击、上滑、读屏、等待。
   任何"发送消息/发帖/购买/删除/卸载/安装/修改设置/关注/点赞/转账"都是**外向动作**，
   **绝不能写进 code 直接执行**。
2. 若指令含外向动作，必须把该步标成 needs_confirm=true，confirm_text 用中文说明
   你要做什么（例如"在微信里向 X 发送消息？"），code 里只写"导航到那一步"的只读操作
   （如 H.launch、H.tap_text 点到输入框），真正的外向触发交给人确认。
3. 若指令本身含糊、无法安全执行，输出 {"error": "中文原因"}。
4. 只输出一个 JSON 对象，不要 markdown 代码块围栏、不要解释文字。

输出格式（JSON）：
{
  "plan_text": "用一句话中文描述你打算怎么做",
  "steps": [
    {"name": "步骤名（人类可读，如"检查是否已安装"）", "code": "该步的python代码", "needs_confirm": false},
    {"name": "…", "code": "…", "needs_confirm": true, "confirm_text": "确认提示"}
  ]
}"""


def _parse_json(text: str):
    """Parse a JSON object out of an LLM reply, tolerating stray fences."""
    t = text.strip()
    if t.startswith("```"):
        # strip ```json ... ``` fence
        t = t.split("\n", 1)[-1]
        if "```" in t:
            t = t.rsplit("```", 1)[0]
        t = t.strip()
    try:
        data = json.loads(t)
    except json.JSONDecodeError:
        # try to find the first { ... } block
        s, e = t.find("{"), t.rfind("}")
        if s == -1 or e == -1:
            raise ValueError("LLM 未返回 JSON: %s" % text[:200])
        data = json.loads(t[s:e + 1])
    if not isinstance(data, dict):
        raise ValueError("计划不是对象")
    return data


def plan(prompt: str) -> dict:
    """Translate a Chinese instruction into a structured plan.

    Returns:
        {"plan_text": str, "steps": [{"name","code","needs_confirm",
                                      "confirm_text"?}]}
    or raises on LLM / parse failure. Each step's code is still a string; the
    caller (web.py) AST-whitelists it before running.
    """
    data = _parse_json(_chat(_PLAN_SYSTEM, prompt.strip()))
    if "error" in data:
        raise RuntimeError(str(data["error"]))
    plan_text = str(data.get("plan_text", "执行你的指令"))
    raw_steps = data.get("steps") or []
    steps = []
    for s in raw_steps:
        if not isinstance(s, dict):
            continue
        name = str(s.get("name", "步骤"))
        code = str(s.get("code", ""))
        nc = bool(s.get("needs_confirm", False))
        step = {"name": name, "code": code, "needs_confirm": nc}
        if nc and s.get("confirm_text"):
            step["confirm_text"] = str(s["confirm_text"])
        steps.append(step)
    return {"plan_text": plan_text, "steps": steps}

