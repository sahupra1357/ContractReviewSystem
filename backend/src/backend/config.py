from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CRS_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://crs:crs@localhost:5433/crs"
    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket_raw: str = "raw"
    s3_bucket_masked: str = "masked"
    s3_bucket_audit: str = "audit"
    presidio_analyzer_url: str = "http://localhost:5002"
    presidio_anonymizer_url: str = "http://localhost:5001"
    # LLM adapter — multi-provider (design §3.5); endpoints/keys from config only
    # anthropic | bedrock | openai | nvidia | mistral | minimax | kimi | qwen
    llm_provider: str = "anthropic"
    llm_model_strong: str | None = None  # None → provider default
    llm_model_fast: str | None = None
    llm_api_key: str | None = None       # None → SDK env resolution (anthropic)
    llm_base_url: str | None = None      # None → provider default / ANTHROPIC_BASE_URL
    aws_region: str = "us-east-1"        # bedrock only
    environment: str = "local"


@lru_cache
def get_settings() -> Settings:
    return Settings()
