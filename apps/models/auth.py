from pydantic import BaseModel, Field


class OAuth2CodeRequest(BaseModel):
    code: str = Field(..., min_length=1)
