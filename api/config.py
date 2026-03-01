from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    gcp_project_id: str
    api_key: str
    cache_ttl_days: int = 14
    storage_file: str = "linkedin_storage.json"
    jobs_collection: str = "jobs"
    cache_collection: str = "cache"

    model_config = {"env_file": ".env"}


settings = Settings()
