from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: SecretStr = SecretStr("")
    cue_bootstrap_secret: SecretStr = SecretStr("")
    cue_token_ttl_minutes: int = Field(default=10, ge=1, le=60)
    cue_cors_origins: str = "http://localhost:5173"

    @property
    def livekit_configured(self) -> bool:
        return bool(
            self.livekit_url
            and self.livekit_api_key
            and self.livekit_api_secret.get_secret_value()
            and self.cue_bootstrap_secret.get_secret_value()
        )

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cue_cors_origins.split(",") if origin.strip()]
