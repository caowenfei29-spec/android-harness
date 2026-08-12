"""LLM bridge for mobile_superagent (OpenAI-compatible).

Reads credentials from settings/.env only. The key never leaves this process
and is never printed/logged in cleartext.
"""
import json
import urllib.error
import urllib.request

from ..settings import settings


def configured() -> bool:
    return bool(settings.llm_api_key and settings.llm_base_url)


class LLMClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None,
                 model: str | None = None, timeout: int | None = None):
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.llm_api_key
        self.model = model or settings.llm_model
        self.timeout = timeout or settings.llm_timeout

    def chat(self, system: str, messages: list[dict]) -> str:
        """messages: list of {role, content} in chronological order."""
        if not self.api_key:
            raise RuntimeError(
                "LLM 未配置：在 .env 设置 LLM_API_KEY（key 只存本地，不外泄）")
        msgs = [{"role": "system", "content": system}] + [
            m for m in messages if m.get("content")]
        body = json.dumps({
            "model": self.model,
            "messages": msgs,
            "temperature": 0.2,
        }).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self.api_key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(f"LLM HTTP {e.code}: {detail}")
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"LLM 调用失败: {e}")
