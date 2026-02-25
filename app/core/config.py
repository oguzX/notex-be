"""Application configuration using Pydantic settings."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Environment
    ENV: Literal["development", "production", "test"] = "development"
    DEBUG: bool = True
    
    # API
    API_V1_PREFIX: str = "/v1"
    PROJECT_NAME: str = "Notex"
    
    # CORS
    CORS_ORIGINS: list[str] = Field(
        default=["http://localhost:3000", "http://localhost:5173"],
    )
    CORS_CREDENTIALS: bool = True
    CORS_METHODS: list[str] = Field(default=["*"])
    CORS_HEADERS: list[str] = Field(default=["*"])
    
    # Database
    DATABASE_URL: PostgresDsn = Field(
        default="postgresql+asyncpg://notex:notex@localhost:5432/notex"
    )
    DB_ECHO: bool = False
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    
    # Redis
    REDIS_URL: RedisDsn = Field(default="redis://localhost:6379/0")
    REDIS_DECODE_RESPONSES: bool = True
    
    # Celery
    CELERY_BROKER_URL: str = Field(default="redis://localhost:6379/1")
    CELERY_RESULT_BACKEND: str = Field(default="redis://localhost:6379/2")
    CELERY_TASK_TRACK_STARTED: bool = True
    CELERY_TASK_TIME_LIMIT: int = 300  # 5 minutes
    CELERY_TASK_SOFT_TIME_LIMIT: int = 270
    
    # LLM
    LLM_PROVIDER: Literal["openai", "gemini"] = "openai"
    OPENAI_API_KEY: str | None = None
    OPENAI_MODEL: str = "gpt-4o"
    OPENAI_TIMEOUT: int = 30
    GEMINI_API_KEY: str | None = None
    GEMINI_MODEL: str = "gemini-2.0-flash-exp"
    GEMINI_TIMEOUT: int = 30
    
    # MCP (Model Context Protocol)
    MCP_SERVER_URL: str = Field(default="http://mcp_http:8001/sse")
    MCP_ENABLED: bool = True
    
    # Logging
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    LOG_FORMAT: Literal["json", "console"] = "json"
    
    # Events
    EVENTS_STREAM_PREFIX: str = "stream:events:"
    EVENTS_PUBSUB_PREFIX: str = "events:"
    EVENTS_MAX_STREAM_LEN: int = 10000
    
    # Business logic
    CONTEXT_MESSAGE_LIMIT: int = 20
    RESOLVER_CONFIDENCE_THRESHOLD: float = 0.65
    RESOLVER_TIME_WINDOW_MINUTES: int = 45
    RESOLVER_MAX_CANDIDATES: int = 5
    
    # Authentication
    JWT_SECRET: str = Field(default="change-me-in-production-use-long-random-string")
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_TTL_SECONDS: int = 7200  # 2 hours
    REFRESH_TOKEN_TTL_SECONDS: int = 2592000  # 30 days
    
    # Push Notifications (OneSignal)
    # Note: notification_token in Device model stores OneSignal player_id/subscription_id
    NOTIFICATIONS_ENABLED: bool = True
    ONESIGNAL_APP_ID: str | None = None
    ONESIGNAL_REST_API_KEY: str | None = None  # Server REST API key
    ONESIGNAL_API_BASE: str = "https://onesignal.com/api/v1"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
