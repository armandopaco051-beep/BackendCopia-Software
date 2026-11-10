from fastapi import APIRouter, Depends, Path, Query, Header, HTTPException
from fastapi import File, Form, UploadFile
from sqlalchemy.orm import Session
from typing import Literal

from app.database import get_db
from app.models.usuario import Usuario
from app.schemas.chat import (
    ConversacionCreate, ConversacionResponse, MensajeCreate,
    MensajeResponse, MensajesResponse,
)
from app.security.auth_dependencies import get_current_user
from app.services.chat import crear_mensaje, listar_mensajes, obtener_o_crear_conversacion
from app.services.chat import obtener_contexto_chat
from app.services.chat_ia import generar_respuesta
from app.services.chat_ia import analizar_imagen
from app.schemas.chat import ConsultaImagenResponse

router = APIRouter(tags=["Chat"])


@router.post("/conversaciones/{conversacion_id}/imagen", response_model=ConsultaImagenResponse)
def imagen_chat(
    conversacion_id: int = Path(gt=0),
    diagrama_id: int = Form(gt=0),
    image: UploadFile = File(),
    authorization: str = Header(default=""),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "Token requerido")
    content = image.file.read(10 * 1024 * 1024 + 1)
    return analizar_imagen(db, conversacion_id, diagrama_id, content,
                          image.content_type or "", image.filename or "imagen", usuario, token)


@router.get("/conversaciones/{conversacion_id}/contexto")
def contexto_ia(
    conversacion_id: int = Path(gt=0),
    hasta_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    return obtener_contexto_chat(db, conversacion_id, usuario, hasta_id)


@router.post(
    "/conversaciones/{conversacion_id}/mensajes/{mensaje_id}/respuesta-ia",
    response_model=MensajeResponse,
)
def responder_consulta(
    conversacion_id: int = Path(gt=0),
    mensaje_id: int = Path(gt=0),
    expected_diagrama_id: int | None = Query(default=None, gt=0),
    text_provider: Literal["gemini", "local"] = Query(default="gemini"),
    authorization: str = Header(default=""),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "Token requerido")
    return generar_respuesta(db, conversacion_id, mensaje_id, usuario, token, expected_diagrama_id, text_provider)


@router.post("/proyectos/{proyecto_id}/conversaciones", response_model=ConversacionResponse)
def abrir_conversacion(
    datos: ConversacionCreate,
    proyecto_id: int = Path(gt=0),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    return obtener_o_crear_conversacion(db, proyecto_id, datos.tipo, usuario)


@router.get("/conversaciones/{conversacion_id}/mensajes", response_model=MensajesResponse)
def obtener_historial(
    conversacion_id: int = Path(gt=0),
    limite: int = Query(default=50, ge=1, le=100),
    antes_de: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    return listar_mensajes(db, conversacion_id, usuario, limite, antes_de)


@router.post(
    "/conversaciones/{conversacion_id}/mensajes",
    response_model=MensajeResponse, status_code=201,
)
def enviar_mensaje(
    datos: MensajeCreate,
    conversacion_id: int = Path(gt=0),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    return crear_mensaje(db, conversacion_id, datos, usuario)
