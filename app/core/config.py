from pydantic_settings import BaseSettings
from pydantic import field_validator
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    database_url: str

    # JWT
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # Scraper
    target_url: str = ""
    scraper_field_schema: str = "scraper_schema.json"

    # Scheduler (cron string)
    scrape_cron: str = "0 */6 * * *"

    # Rate limiting
    rate_limit: str = "30/minute"

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, v: str) -> str:
        """
        Neon and Render provide postgres:// or postgresql:// URLs.
        SQLAlchemy async requires postgresql+asyncpg://.
        Auto-convert any variant so deployment just works.
        """
        if v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+asyncpg://", 1)
        if v.startswith("postgresql://") and "+asyncpg" not in v:
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
