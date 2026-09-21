from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    app_name: str
    app_env: str
    database: str
    ai_provider_configured: bool
