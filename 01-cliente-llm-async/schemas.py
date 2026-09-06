"""Modelos Pydantic: configuración, mensajes y respuestas del cliente de LLM."""

from enum import Enum

from pydantic import BaseModel, Field, SecretStr, model_validator


class Provider(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class ChatMessage(BaseModel):
    """Un mensaje de la conversación, con la misma forma para todos los proveedores."""

    role: Role
    content: str = Field(min_length=1)


class ModelParams(BaseModel):
    """Parámetros de inferencia validados antes de tocar la red."""

    model: str
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=512, gt=0, le=8192)
    timeout: float = Field(default=30.0, gt=0)


class LLMConfig(BaseModel):
    """Claves de API. `SecretStr` evita que aparezcan en logs o tracebacks."""

    provider: Provider
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None

    @model_validator(mode="after")
    def check_key_for_provider(self) -> "LLMConfig":
        required = {
            Provider.OPENAI: self.openai_api_key,
            Provider.ANTHROPIC: self.anthropic_api_key,
        }[self.provider]
        if required is None or not required.get_secret_value():
            raise ValueError(
                f"Falta la API key para el proveedor '{self.provider.value}'. "
                f"Definila en el archivo .env."
            )
        return self


class ModelResponse(BaseModel):
    """Respuesta normalizada. `ok=False` significa error controlado, no excepción."""

    provider: Provider
    model: str
    content: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    elapsed: float | None = None
    ok: bool = True
    error: str | None = None
