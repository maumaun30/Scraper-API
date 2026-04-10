from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    database_url: str

    # JWT
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # Scraper
    target_url: str
    scraper_field_schema: str = "scraper_schema.json"

    # Scheduler (cron string)
    scrape_cron: str = "0 */6 * * *"

    # Rate limiting
    rate_limit: str = "30/minute"

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
