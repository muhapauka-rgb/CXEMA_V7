from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CXEMA_", env_file=".env", extra="ignore")

    DB_PATH: str = "../data/app.db"
    ADMIN_PIN: str = "1234"
    CORS_ORIGINS: str = "http://localhost:13011,http://127.0.0.1:13011"
    SHEETS_MODE: str = "mock"
    SHEETS_MOCK_DIR: str = "../data/mock_sheets"
    GOOGLE_CLIENT_SECRET_FILE: str = "../data/google/client_secret.json"
    GOOGLE_TOKEN_FILE: str = "../data/google/token.json"
    GOOGLE_OAUTH_REDIRECT_URI: str = "http://localhost:28011/api/google/auth/callback"
    AUTO_BACKUP_MODE: str = "LEGACY"  # LEGACY | MWF_ROLLING_DB
    AUTO_BACKUP_DAYS: str = "MON,WED,FRI"
    AUTO_BACKUP_TIME: str = "23:00"
    AUTO_BACKUP_CURRENT_FILE: str = "app.backup.current.db"
    AUTO_BACKUP_PREV_FILE: str = "app.backup.prev.db"

settings = Settings()
