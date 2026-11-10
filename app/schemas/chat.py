from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ConversacionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tipo: Literal["individual", "grupal"]


class ConversacionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    proyecto_id: int
    tipo: Literal["individual", "grupal"]
    propietario_codigo: str | None
    creado_en: datetime


class MensajeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    texto: str = Field(min_length=1, max_length=10000)
    diagrama_id: int | None = Field(default=None, gt=0)

    @field_validator("texto")
    @classmethod
    def limpiar_texto(cls, valor: str):
        texto = valor.strip()
        if not texto:
            raise ValueError("El mensaje no puede estar vacío")
        return texto


class MensajeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    conversacion_id: int
    diagrama_id: int | None
    rol: Literal["user", "assistant"]
    autor_codigo: str | None
    autor_nombre: str
    texto: str
    resultado_ia: dict[str, Any] | None
    creado_en: datetime


class MensajesResponse(BaseModel):
    mensajes: list[MensajeResponse]
    siguiente_antes_de: int | None = None


class PlanIAResponse(BaseModel):
    intent: str
    summary: str = Field(min_length=1)
    actions: list[dict[str, Any]]
    questions: list[str]
    can_execute: bool
    provider: Literal["gemini", "local"] | None = None
    model: str | None = None


class ConsultaImagenResponse(BaseModel):
    consulta: MensajeResponse
    respuesta: MensajeResponse
