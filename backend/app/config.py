from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Swap for postgresql+psycopg://user:pass@host/dbname in production.
    database_url: str = f"sqlite:///{BASE_DIR / 'data' / 'distribution.db'}"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- GST compliance ------------------------------------------------
    # Thresholds are policy, not physics: they have moved before and will
    # again, so they are settings rather than constants in the code.

    # Interstate B2C invoices above this go to B2CL rather than B2CS.
    b2cl_threshold: int = 100_000

    # HSN digits required in Table 12; 6 for turnover above Rs 5 crore.
    hsn_digits: int = 6

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
