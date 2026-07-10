from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Which Zenodo instance this deployment talks to. This is a deployment-wide
    # choice (not a per-user toggle), matching HTRMoPo's own MODEL_REPO_URL pattern.
    zenodo_env: str = "sandbox"  # "sandbox" | "production"

    zenodo_sandbox_client_id: str = ""
    zenodo_sandbox_client_secret: str = ""
    zenodo_prod_client_id: str = ""
    zenodo_prod_client_secret: str = ""
    zenodo_redirect_uri: str = "http://localhost:8000/api/auth/zenodo/callback"

    session_secret: str = "change-me-in-production"

    database_path: str = "./data/htrmopo-app.db"

    # Per-file cap enforced on model file uploads (Zenodo itself allows up to
    # 50GB/file; this is a smaller app-level guard against filling local disk
    # before a file ever reaches Zenodo -- draft files are staged locally
    # under {database_path parent}/uploads/ until published).
    max_upload_mb: int = 5120

    # Path prefix this app is served under (e.g. "/plop") when there is no
    # dedicated domain and the app lives behind a reverse-proxy subfolder.
    url_base_path: str = ""

    frontend_dist_dir: str = "./static"

    # In-process nightly refresh of the catalog from the public ocr_models
    # Zenodo community (in addition to the refresh already triggered by every
    # publish). No OS-level cron needed -- runs as a background asyncio task
    # for as long as the app process is up.
    enable_nightly_harvest: bool = True
    nightly_harvest_hour_utc: int = 2

    # Python logging level name (e.g. "DEBUG", "INFO", "WARNING") applied to
    # the app's own loggers -- see app.main's logging.basicConfig call.
    # Uvicorn's default logging setup doesn't configure the root logger, so
    # without this INFO-level diagnostics (e.g. the Zenodo OAuth callback
    # logging in app.routers.auth) are silently dropped.
    log_level: str = "INFO"

    @property
    def zenodo_base_url(self) -> str:
        if self.zenodo_env == "production":
            return "https://zenodo.org"
        return "https://sandbox.zenodo.org"

    @property
    def zenodo_api_url(self) -> str:
        return f"{self.zenodo_base_url}/api/"

    @property
    def zenodo_client_id(self) -> str:
        return self.zenodo_prod_client_id if self.zenodo_env == "production" else self.zenodo_sandbox_client_id

    @property
    def zenodo_client_secret(self) -> str:
        return self.zenodo_prod_client_secret if self.zenodo_env == "production" else self.zenodo_sandbox_client_secret


@lru_cache
def get_settings() -> Settings:
    return Settings()
