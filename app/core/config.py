from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://baseline:baseline@localhost:5433/baseline"
    app_name: str = "Baseline"
    debug: bool = False
    scale_scan_timeout: int = 45

    # Garmin auto-sync scheduler (running inside the API lifespan).
    #   sync_interval_min: 0 disables the recurring loop. Catch-up on startup
    #     still runs once if the user/config prerequisites are in place.
    #   baseline_user_id: target user for auto-sync.  Also consumed by
    #     scripts/sync_garmin.py and scripts/import_scale.py as a CLI fallback.
    sync_interval_min: int = 60
    baseline_user_id: str | None = None

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
