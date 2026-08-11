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
