from pydantic_settings import BaseSettings
from pydantic import field_validator
from functools import lru_cache
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse


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
        Neon provides: postgresql://user:pass@host/db?sslmode=require&channel_binding=require
        asyncpg needs:  postgresql+asyncpg://user:pass@host/db?ssl=require

        1. Swap scheme to postgresql+asyncpg://
        2. Replace psycopg2-style params with asyncpg equivalents
        3. Drop unsupported params (channel_binding)
        """
        # Fix scheme
        if v.startswith("postgres://"):
            v = v.replace("postgres://", "postgresql+asyncpg://", 1)
        elif v.startswith("postgresql://") and "+asyncpg" not in v:
            v = v.replace("postgresql://", "postgresql+asyncpg://", 1)

        # Parse and clean query params
        parsed = urlparse(v)
        params = parse_qs(parsed.query, keep_blank_values=True)

        # asyncpg doesn't understand sslmode= — translate to ssl=
        if "sslmode" in params:
            sslmode = params.pop("sslmode")[0]
            # Map psycopg2 sslmode values → asyncpg ssl values
            ssl_map = {
                "require": "require",
                "verify-ca": "require",
                "verify-full": "require",
                "disable": "disable",
                "prefer": "require",
                "allow": "require",
            }
            params["ssl"] = [ssl_map.get(sslmode, "require")]

        # Drop params asyncpg doesn't support
        for unsupported in ("channel_binding", "connect_timeout", "application_name"):
            params.pop(unsupported, None)

        # Rebuild URL
        new_query = urlencode({k: v[0] for k, v in params.items()})
        cleaned = urlunparse(parsed._replace(query=new_query))
        return cleaned

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
