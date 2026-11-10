from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session

from app.database import SessionLocal
from starlette.concurrency import run_in_threadpool
from app.models.usuario import Usuario
from app.security.jwt import verificar_token
from app.services.diagrama import obtener_diagrama
from app.services.proyecto import usuario_tiene_permiso
from app.services.realtime_manager import realtime_manager, utc_now_iso


router = APIRouter(tags=["Tiempo real"])


EDIT_EVENTS = {
    "class_created",
    "class_updated",
    "class_deleted",
    "class_moved",
    "relation_created",
    "relation_updated",
    "relation_deleted",
    "diagram_saved",
    "diagram_reloaded",
}

VIEW_EVENTS = {
    "cursor_moved",
    "selection_changed",
    "typing_started",
    "typing_stopped",
    "comment_created",
    "comment_updated",
    "comment_resolved",
    "comment_deleted",
}


ALLOWED_EVENTS = EDIT_EVENTS | VIEW_EVENTS


def get_user_from_token(db: Session, token: str | None):
    if not token:
        return None

    payload = verificar_token(token)

    if payload is None:
        return None

    codigo = payload.get("sub")

    if not codigo:
        return None

    return db.query(Usuario).filter(Usuario.codigo == codigo).first()


def user_payload(usuario: Usuario, can_edit: bool):
    nombre = " ".join([usuario.nombres or "", usuario.apellidos or ""]).strip()

    return {
        "codigo": usuario.codigo,
        "nombre": nombre or usuario.email,
        "email": usuario.email,
        "can_edit": can_edit,
    }


def build_realtime_event(
    event_type: str,
    diagrama_id: int,
    user: dict[str, Any],
    payload: Any,
):
    return {
        "type": event_type,
        "diagrama_id": diagrama_id,
        "user": user,
        "payload": payload if isinstance(payload, dict) else {},
        "timestamp": utc_now_iso(),
    }


def load_socket_identity(diagrama_id: int, token: str | None):
    # La sesión termina ANTES de aceptar el WebSocket; no se retiene una
    # transacción PostgreSQL durante toda la conversación en tiempo real.
    with SessionLocal() as db:
        usuario = get_user_from_token(db, token)
        if usuario is None:
            return None
        diagrama = obtener_diagrama(db, diagrama_id)
        if diagrama is None:
            return None
        if not usuario_tiene_permiso(db, diagrama.id_proyecto, usuario.codigo, "ver_diagrama"):
            return None
        can_edit = usuario_tiene_permiso(db, diagrama.id_proyecto, usuario.codigo, "editar_diagrama")
        return user_payload(usuario, can_edit)


@router.websocket("/ws/diagramas/{diagrama_id}")
async def diagram_realtime_socket(
    websocket: WebSocket,
    diagrama_id: int,
    token: str | None = Query(default=None),
):
    current_user = await run_in_threadpool(load_socket_identity, diagrama_id, token)
    if current_user is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    can_edit = current_user["can_edit"]

    await realtime_manager.connect(diagrama_id, websocket, current_user)

    await websocket.send_json(
        {
            "type": "connection_ack",
            "diagrama_id": diagrama_id,
            "user": current_user,
            "users": await realtime_manager.get_users(diagrama_id),
            "timestamp": utc_now_iso(),
        }
    )

    await realtime_manager.broadcast(
        diagrama_id,
        build_realtime_event("user_joined", diagrama_id, current_user, {}),
        exclude=websocket,
    )

    try:
        while True:
            data = await websocket.receive_json()
            event_type = data.get("type")
            payload = data.get("payload") or {}

            if event_type not in ALLOWED_EVENTS:
                await websocket.send_json(
                    {
                        "type": "event_rejected",
                        "reason": "EVENTO_NO_PERMITIDO",
                        "event_type": event_type,
                        "timestamp": utc_now_iso(),
                    }
                )
                continue

            if event_type in EDIT_EVENTS and not can_edit:
                await websocket.send_json(
                    {
                        "type": "event_rejected",
                        "reason": "SIN_PERMISO_EDICION",
                        "event_type": event_type,
                        "timestamp": utc_now_iso(),
                    }
                )
                continue

            await realtime_manager.broadcast(
                diagrama_id,
                build_realtime_event(event_type, diagrama_id, current_user, payload),
                exclude=websocket,
            )

    except WebSocketDisconnect:
        pass
    finally:
        disconnected_user = await realtime_manager.disconnect(diagrama_id, websocket)

        if disconnected_user:
            await realtime_manager.broadcast(
                diagrama_id,
                build_realtime_event("user_left", diagrama_id, disconnected_user, {}),
            )
