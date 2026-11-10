from pydantic_settings import BaseSettings 

class Settings(BaseSettings): 
    DATABASE_URL: str
    SECRET_KEY: str
    ALGORITHM: str = "HS256"    
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 20
    AI_API_URL: str = "https://iabackend-copia.onrender.com"
    AI_REQUEST_TIMEOUT: float = 180.0

    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()
