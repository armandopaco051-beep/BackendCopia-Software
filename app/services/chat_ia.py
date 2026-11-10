import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models.chat import Mensaje
from app.models.diagrama import Diagrama
from app.models.usuario import Usuario
from app.schemas.chat import PlanIAResponse
from app.services.chat import obtener_conversacion_autorizada


def solicitar_ia(path: str, body: bytes, token: str, content_type: str = "application/json"):
    request = Request(
        settings.AI_API_URL.rstrip("/") + path, data=body,
        headers={"Content-Type": content_type, "Authorization": f"Bearer {token}"},
    )
    try:
        with urlopen(request, timeout=settings.AI_REQUEST_TIMEOUT) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError("AI response too large")
        return json.loads(raw)
    except HTTPError as exc:
        try:
            detail = json.loads(exc.read(8192)).get("detail")
        except (ValueError, AttributeError):
            detail = None
        finally:
            exc.close()
        if isinstance(detail, dict) and detail.get("code") in {
            "LOCAL_OUTPUT_TRUNCATED", "LOCAL_UNAVAILABLE", "LOCAL_TIMEOUT", "LOCAL_HTTP_ERROR", "LOCAL_INVALID_RESPONSE",
        } and isinstance(detail.get("message"), str):
            raise HTTPException(502, "Tu consulta está guardada. " + detail["message"][:500]) from exc
        raise HTTPException(502, "Tu consulta está guardada, pero el servicio IA no pudo responder. Puedes reintentar.") from exc
    except (TimeoutError, URLError) as exc:
        raise HTTPException(504, "Tu consulta está guardada. La IA no respondió a tiempo; puedes reintentar.") from exc
    except ValueError as exc:
        raise HTTPException(502, "La IA devolvió una respuesta inválida; tu consulta sigue guardada.") from exc


def generar_respuesta(db: Session, conversacion_id: int, mensaje_id: int, usuario: Usuario, token: str,
                     expected_diagrama_id: int | None = None, text_provider: str = "gemini"):
    if text_provider not in {"gemini", "local"}:
        raise HTTPException(422, "Proveedor de texto no permitido")
    conversacion = obtener_conversacion_autorizada(db, conversacion_id, usuario)
    consulta = db.query(Mensaje).filter(
        Mensaje.id == mensaje_id, Mensaje.conversacion_id == conversacion_id,
        Mensaje.rol == "user", Mensaje.autor_codigo == usuario.codigo,
    ).first()
    if consulta is None:
        raise HTTPException(404, "Consulta no encontrada")
    if expected_diagrama_id is not None and consulta.diagrama_id != expected_diagrama_id:
        raise HTTPException(409, "Esta consulta pertenece a otro diagrama. Abre su diagrama original o envía una consulta nueva.")
    existente = db.query(Mensaje).filter(
        Mensaje.conversacion_id == conversacion_id,
        Mensaje.resultado_ia["reply_to"].astext == str(mensaje_id),
        Mensaje.rol == "assistant",
    ).first()
    if existente is not None:
        return existente
    proyecto_id, diagrama_id, texto = conversacion.proyecto_id, consulta.diagrama_id, consulta.texto
    version = None
    if diagrama_id is not None:
        diagrama = db.query(Diagrama).filter(
            Diagrama.id == diagrama_id, Diagrama.id_proyecto == proyecto_id,
        ).first()
        if diagrama is None:
            raise HTTPException(404, "Diagrama no encontrado")
        version = diagrama.version
    # Release the read transaction while the remote/local model generates.
    db.rollback()
    body = json.dumps({
        "message": texto, "proyecto_id": proyecto_id, "diagrama_id": diagrama_id,
        "conversacion_id": conversacion_id, "mensaje_id": mensaje_id,
        "text_provider": text_provider,
    }).encode("utf-8")
    try:
        plan = PlanIAResponse.model_validate(solicitar_ia("/ai/planner", body, token))
    except ValidationError as exc:
        raise HTTPException(502, "La IA devolvió una respuesta inválida; tu consulta sigue guardada.") from exc
    # Membership may have changed while the request was running.
    obtener_conversacion_autorizada(db, conversacion_id, usuario)
    result = plan.model_dump()
    result.update(
        reply_to=str(mensaje_id), diagrama_version=version,
        destinatario_codigo=usuario.codigo,
        destinatario_nombre=" ".join(filter(None, [usuario.nombres, usuario.apellidos])).strip() or usuario.codigo,
        provider=text_provider,
    )
    respuesta = Mensaje(
        conversacion_id=conversacion_id, diagrama_id=diagrama_id,
        rol="assistant", autor_codigo=None, autor_nombre="Asistente IA",
        texto=plan.summary, resultado_ia=result,
    )
    try:
        db.add(respuesta)
        db.commit()
        db.refresh(respuesta)
        return respuesta
    except IntegrityError:
        db.rollback()
        existente = db.query(Mensaje).filter(
            Mensaje.conversacion_id == conversacion_id,
            Mensaje.resultado_ia["reply_to"].astext == str(mensaje_id),
            Mensaje.rol == "assistant",
        ).first()
        if existente is not None:
            return existente
        raise


def analizar_imagen(db: Session, conversacion_id: int, diagrama_id: int, image: bytes,
                    mime_type: str, filename: str, usuario: Usuario, token: str):
    from uuid import uuid4
    from app.schemas.chat import MensajeCreate
    from app.services.chat import crear_mensaje

    if mime_type not in {"image/png", "image/jpeg", "image/webp"}:
        raise HTTPException(415, "La imagen debe ser PNG, JPEG o WebP")
    if not image or len(image) > 10 * 1024 * 1024:
        raise HTTPException(413, "La imagen debe tener contenido y no superar 10 MB")
    consulta = crear_mensaje(db, conversacion_id, MensajeCreate(
        texto=f"Imagen: {filename[:200]}", diagrama_id=diagrama_id,
    ), usuario)
    consulta_id = consulta.id
    conversacion = obtener_conversacion_autorizada(db, conversacion_id, usuario)
    proyecto_id = conversacion.proyecto_id
    diagrama = db.query(Diagrama).filter(Diagrama.id == diagrama_id).one()
    version = diagrama.version
    db.rollback()
    boundary = "chat-" + uuid4().hex
    chunks = []
    for key, value in {"proyecto_id": proyecto_id, "diagrama_id": diagrama_id,
                       "message": "Extrae fielmente las clases y relaciones visibles."}.items():
        chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
    chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="diagram"\r\nContent-Type: {mime_type}\r\n\r\n'.encode())
    chunks.extend([image, f"\r\n--{boundary}--\r\n".encode()])
    result = solicitar_ia("/ai/image/analyze", b"".join(chunks), token, f"multipart/form-data; boundary={boundary}")
    try:
        plan = PlanIAResponse.model_validate({**result, "intent": "modify_diagram"})
    except (ValidationError, TypeError) as exc:
        raise HTTPException(502, "No se pudo validar el análisis de la imagen") from exc
    obtener_conversacion_autorizada(db, conversacion_id, usuario)
    payload = plan.model_dump()
    payload.update(reply_to=str(consulta_id), diagrama_version=version,
                   provider="gemini", model=(result.get("image_metadata") or {}).get("model"),
                   destinatario_codigo=usuario.codigo,
                   destinatario_nombre=" ".join(filter(None, [usuario.nombres, usuario.apellidos])).strip() or usuario.codigo,
                   warnings=result.get("warnings", []),
                   imageStats={"classes": len(result.get("classes", [])), "relations": len(result.get("relations", []))})
    respuesta = Mensaje(conversacion_id=conversacion_id, diagrama_id=diagrama_id,
        rol="assistant", autor_codigo=None, autor_nombre="Asistente IA",
        texto=plan.summary, resultado_ia=payload)
    try:
        db.add(respuesta)
        db.commit()
        db.refresh(respuesta)
        consulta = db.query(Mensaje).filter(Mensaje.id == consulta_id).one()
        return {"consulta": consulta, "respuesta": respuesta}
    except Exception:
        db.rollback()
        raise
