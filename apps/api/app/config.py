from pydantic import Field, AliasChoices
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://coldsync:coldsync@localhost:5432/coldsync"
    chroma_host: str = ""
    chroma_port: int = 8000
    api_cors_origins: str = "http://localhost:3000"
    evidence_storage_dir: str = "./data/evidence"
    max_evidence_file_size_mb: int = Field(default=15, ge=1, le=100)
    historical_case_dataset_path: str | None = None
    sbert_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    sbert_batch_size: int = Field(default=32, ge=1, le=512)
    sbert_device: str = "auto"
    chroma_persist_directory: str = "./data/chroma"
    clip_model_name: str = "openai/clip-vit-base-patch32"
    clip_device: str = "auto"
    clip_batch_size: int = Field(default=8, ge=1, le=128)
    historical_image_storage_dir: str = "./data/historical_images"
    serpapi_api_key: str = ""
    serpapi_default_engine: str = "google"
    serpapi_default_gl: str = "in"
    serpapi_default_hl: str = "en"
    serpapi_timeout_seconds: float = Field(default=15, ge=1, le=60)
    serpapi_max_results_per_query: int = Field(default=10, ge=1, le=100)
    serpapi_max_queries_per_run: int = Field(default=6, ge=1, le=20, validation_alias=AliasChoices("SERPAPI_MAX_QUERIES_PER_RUN", "SERPAPI_MAX_QUERIES_PER_RESEARCH_RUN"))
    max_search_query_length: int = Field(default=500, ge=1, le=2000)
    serpapi_mock_mode: bool = False
    research_rate_limit_per_minute: int = Field(default=5, ge=1, le=60)
    agent_max_iterations: int = Field(default=5, ge=1, le=20)
    agent_max_actions_per_iteration: int = Field(default=3, ge=1, le=10)
    agent_max_serpapi_queries: int = Field(default=10, ge=0, le=50)
    agent_max_results: int = Field(default=50, ge=1, le=500)
    agent_max_historical_searches: int = Field(default=5, ge=0, le=20)
    agent_max_image_searches: int = Field(default=5, ge=0, le=20)
    agent_max_total_actions: int = Field(default=20, ge=1, le=100)

    @field_validator("sbert_device")
    @classmethod
    def supported_sbert_device(cls, value: str) -> str:
        value = value.lower().strip()
        if value not in {"auto", "cpu", "cuda"}:
            raise ValueError("SBERT_DEVICE must be auto, cpu, or cuda")
        return value

    @field_validator("clip_device")
    @classmethod
    def supported_clip_device(cls, value: str) -> str:
        value = value.lower().strip()
        if value not in {"auto", "cpu", "cuda"}:
            raise ValueError("CLIP_DEVICE must be auto, cpu, or cuda")
        return value

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.api_cors_origins.split(",") if origin.strip()]


settings = Settings()
