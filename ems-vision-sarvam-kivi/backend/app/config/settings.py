from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    # The key may sit in this repo's .env or in the parent project folder's .env.
    model_config = SettingsConfigDict(env_file=(REPO_DIR.parent / ".env", REPO_DIR / ".env"), extra="ignore")

    sarvam_api_key: str = ""
    sarvam_base_url: str = "https://api.sarvam.ai"
    chat_model: str = "sarvam-105b"
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'data' / 'ems.db').as_posix()}"
    data_dir: Path = BACKEND_DIR / "data"
    kivi_space: Path = BACKEND_DIR / "data" / "kivi_space"
    cors_origins: str = "http://localhost:3000"
    # When set, every API and WebSocket call must present this token.
    app_access_token: str = ""
    # Off on a public host so feed URLs cannot be aimed at the server's own network.
    allow_private_feed_urls: bool = True
    force_demo_mode: bool = False

    @property
    def demo_mode(self) -> bool:
        return self.force_demo_mode or not self.sarvam_api_key


settings = Settings()
