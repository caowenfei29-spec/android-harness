"""App settings for mobile_superagent.

Credentials live in .env (gitignored). We never print/read API keys in
cleartext beyond loading them for the LLM client. Loaded once at import.
"""
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]  # mobile_superagent dir
ENV_FILE = ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ENV_FILE), extra="ignore")

    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-chat"
    llm_timeout: int = 60
    max_steps: int = 40
    db_url: str = f"sqlite:///{ROOT / 'storage' / 'app.db'}"
    storage_dir: str = str(ROOT / "storage" / "runs")
    tessdata_dir: str = str(ROOT / "tessdata")
    tesseract_cmd: str = "C:/Program Files/Tesseract-OCR/tesseract.exe"
    default_timezone: str = "Asia/Shanghai"
    host: str = "127.0.0.1"
    port: int = 8000

    # adapter for the device bridge (reuses the proven adb.py under the hood)
    # ROOT = mobile_superagent dir; the shared android_harness package lives
    # one level up at <repo>/src
    harness_pkg_root: str = str(ROOT.parent / "src")


settings = Settings()
