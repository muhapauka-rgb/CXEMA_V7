from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CXEMA_", env_file=".env", extra="ignore")

    DB_PATH: str = "../data/app.db"
    ADMIN_PIN: str = "1234"
    CORS_ORIGINS: str = "http://localhost:3011"

settings = Settings()
