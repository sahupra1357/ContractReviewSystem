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
    # OCR confidence-gated engine chain (design §3.2). Ordered cheapest-first;
    # a page below the threshold retries the next engine, best result wins.
    # Engines whose library isn't installed are skipped (see the `ocr` extra).
    ocr_engine_chain: str = "tesseract,paddleocr,easyocr,docling"
    ocr_confidence_threshold: float = 0.80
    # Large-document handling (design §3.2): OCR runs in bounded page batches so
    # peak memory is one batch of rasterized images, not the whole document; a
    # completed batch is checkpointed so a crash resumes mid-document. Documents
    # above the page cap park in extract_hold (reason "oversized") for a human.
    ocr_batch_size: int = 16
    extract_max_pages: int = 1000
    # LLM adapter — multi-provider (design §3.5); endpoints/keys from config only
    # anthropic | bedrock | openai | nvidia | mistral | minimax | kimi | qwen
    llm_provider: str = "anthropic"
    llm_model_strong: str | None = None  # None → provider default
    llm_model_fast: str | None = None
    llm_api_key: str | None = None       # None → SDK env resolution (anthropic)
    llm_base_url: str | None = None      # None → provider default / ANTHROPIC_BASE_URL
    aws_region: str = "us-east-1"        # bedrock only
    jwt_secret: str = "dev-secret-change-me"  # POC only; Cognito in production
    static_dir: str | None = None  # built React UI (set in the container image)
    environment: str = "local"


@lru_cache
def get_settings() -> Settings:
    return Settings()
