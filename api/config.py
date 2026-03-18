from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    gcp_project_id: str
    api_key: str
    cache_ttl_days: int = 90
    storage_file: str = "linkedin_storage.json"
    jobs_collection: str = "jobs"
    cache_collection: str = "cache"
    database_id: str = "linkedin-api"
    pubsub_topic: str = "linkedin-jobs"           # Pub/Sub topic name
    pubsub_subscription: str = "linkedin-jobs-local"  # Pull subscription for local worker

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
