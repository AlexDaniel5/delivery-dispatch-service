"""Application configuration."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings, overridable via environment variables (prefix ``DISPATCH_``)."""

    model_config = SettingsConfigDict(env_prefix="DISPATCH_", env_file=".env")

    database_url: str = "sqlite:///./dispatch.db"

    # Maximum pickup distance (km) a courier may be from an order to be eligible.
    assignment_radius_km: float = 10.0

    # Assumed average courier speed used for the ETA estimate.
    courier_speed_kmh: float = 30.0

    # Emit one JSON log line per HTTP request.
    request_logging: bool = True

    # Create tables on startup. Disable in production and use Alembic migrations.
    auto_create_tables: bool = True

    # Comma-separated API keys accepted on write endpoints. Empty disables auth.
    api_keys: str = ""

    @property
    def api_key_set(self) -> frozenset[str]:
        """Parsed, de-duplicated set of configured API keys."""
        return frozenset(key.strip() for key in self.api_keys.split(",") if key.strip())

    @property
    def auth_enabled(self) -> bool:
        """True when at least one API key is configured."""
        return bool(self.api_key_set)


@lru_cache
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance."""
    return Settings()
