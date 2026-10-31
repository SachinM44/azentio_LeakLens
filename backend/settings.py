"""Runtime settings, read once from the environment and `.env` (python-dotenv via pydantic-settings)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(REPO_ROOT / ".env"), env_file_encoding="utf-8", extra="ignore")

    leaklens_api_key: str = Field(default="change-me", description="Value expected in the X-API-Key header")
    api_actor: str = Field(default="reviewer", description="Actor name written to the audit log for API-key calls")
    mongodb_uri: Optional[str] = Field(default=None, description="When set, the MongoDB store is used")
    mongodb_db: str = Field(default="leaklens", description="Database name when MongoDB is used")
    data_dir: Path = Field(default=Path("data/store"), description="Local JSON store root (relative to the repo)")
    cost_cap_usd_per_claim: float = Field(default=2.0, description="Spend cap per claim, surfaced on the run")
    answer_key_path: Path = Field(default=Path("data/synthetic/out/answer_key.json"), description="Hidden answer key")
    documents_manifest_path: Path = Field(default=Path("data/synthetic/out/documents_manifest.json"),
                                          description="Synthetic documents manifest: document facts and types per claim")
    products_dir: Path = Field(default=Path("data/config/products"), description="Seed product configs (*.json)")
    policies_dir: Path = Field(default=Path("data/policies"), description="Policy wording per product: <product_id>.md")
    documents_offline: bool = Field(default=False, description="Document models answer from the cache only (no network)")
    investigator_enabled: bool = Field(default=True, description="Run the investigator agent over suspected findings")

    @property
    def data_dir_abs(self) -> Path:
        return self.data_dir if self.data_dir.is_absolute() else REPO_ROOT / self.data_dir

    @property
    def answer_key_abs(self) -> Path:
        return self.answer_key_path if self.answer_key_path.is_absolute() else REPO_ROOT / self.answer_key_path

    @property
    def products_dir_abs(self) -> Path:
        return self.products_dir if self.products_dir.is_absolute() else REPO_ROOT / self.products_dir

    @property
    def documents_manifest_abs(self) -> Path:
        path = self.documents_manifest_path
        return path if path.is_absolute() else REPO_ROOT / path

    @property
    def policies_dir_abs(self) -> Path:
        return self.policies_dir if self.policies_dir.is_absolute() else REPO_ROOT / self.policies_dir

    def cache_dir_for(self, claim_id: str) -> Path:
        """Model-call cache per claim (under the gitignored store)."""
        return self.data_dir_abs / "cache" / claim_id


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings() -> None:
    """Drop the cached settings (tests change DATA_DIR between runs)."""
    get_settings.cache_clear()
