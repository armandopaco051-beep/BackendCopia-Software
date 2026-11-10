from fastapi import HTTPException
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.chat import Conversacion, Mensaje
from app.models.diagrama import Diagrama
from app.models.usuario import Usuario
from app.schemas.chat import MensajeCreate
from app.services.proyecto import usuario_tiene_permiso, obtener_miembro_proyecto, normalizar_rol


def obtener_contexto_chat(db: Session, conversacion_id: int, usuario: Usuario, hasta_id: int | None = None):
    conversacion = obtener_conversacion_autorizada(db, conversacion_id, usuario)
    consulta_actual = None
    if hasta_id is not None:
        consulta = db.query(Mensaje).filter(
            Mensaje.id == hasta_id,
            Mensaje.conversacion_id == conversacion_id,
            Mensaje.rol == "user",
            Mensaje.autor_codigo == usuario.codigo,
        ).first()
        if consulta is None:
            raise HTTPException(404, "La consulta no pertenece al usuario autenticado en esta conversación")
        consulta_actual = {
            "id": consulta.id, "autor_codigo": usuario.codigo,
            "autor_nombre": " ".join(filter(None, [usuario.nombres, usuario.apellidos])).strip(),
            "texto": consulta.texto, "diagrama_id": consulta.diagrama_id,
        }
    miembro = obtener_miembro_proyecto(db, conversacion.proyecto_id, usuario.codigo)
    rol = normalizar_rol(miembro.rol.nombre) if miembro and miembro.rol else None
    pagina = listar_mensajes(
        db, conversacion_id, usuario, 20, hasta_id + 1 if hasta_id else None,
        diagrama_id=consulta_actual["diagrama_id"] if consulta_actual else None,
        filtrar_diagrama=consulta_actual is not None,
    )
    return {
        "conversacion_id": conversacion.id,
        "proyecto_id": conversacion.proyecto_id,
        "tipo": conversacion.tipo,
        "solicitante": {
            "codigo": usuario.codigo,
            "nombre": " ".join(filter(None, [usuario.nombres, usuario.apellidos])).strip() or usuario.codigo,
            "rol_proyecto": rol,
        },
        "consulta_actual": consulta_actual,
        "diagrama_activo_id": consulta_actual["diagrama_id"] if consulta_actual else None,
        "mensajes": [
            {"id": m.id, "rol": m.rol, "autor_codigo": m.autor_codigo,
             "autor_nombre": m.autor_nombre, "texto": m.texto[:2500], "diagrama_id": m.diagrama_id,
             "en_respuesta_a": (m.resultado_ia or {}).get("reply_to"),
             "destinatario_codigo": (m.resultado_ia or {}).get("destinatario_codigo")}
            for m in pagina["mensajes"]
        ],
    }


def verificar_acceso_proyecto(db: Session, proyecto_id: int, usuario_codigo: str):
    if not usuario_tiene_permiso(db, proyecto_id, usuario_codigo, "ver_proyecto"):
        raise HTTPException(403, "No tienes acceso al chat de este proyecto")


def obtener_o_crear_conversacion(db: Session, proyecto_id: int, tipo: str, usuario: Usuario):
    if tipo not in {"individual", "grupal"}:
        raise HTTPException(422, "Tipo de conversación inválido")
    verificar_acceso_proyecto(db, proyecto_id, usuario.codigo)
    propietario = usuario.codigo if tipo == "individual" else None
    statement = insert(Conversacion).values(
        proyecto_id=proyecto_id, tipo=tipo, propietario_codigo=propietario,
    ).on_conflict_do_nothing()
    try:
        # Partial unique indexes also handle simultaneous opens of the same chat.
        db.execute(statement)
        conversacion = db.query(Conversacion).filter(
            Conversacion.proyecto_id == proyecto_id,
            Conversacion.tipo == tipo,
            Conversacion.propietario_codigo == propietario,
        ).one()
        db.commit()
        db.refresh(conversacion)
        return conversacion
    except Exception:
        db.rollback()
        raise


def obtener_conversacion_autorizada(db: Session, conversacion_id: int, usuario: Usuario):
    conversacion = db.query(Conversacion).filter(Conversacion.id == conversacion_id).first()
    if conversacion is None or (
        conversacion.tipo == "individual"
        and conversacion.propietario_codigo != usuario.codigo
    ):
        raise HTTPException(404, "Conversación no encontrada")
    verificar_acceso_proyecto(db, conversacion.proyecto_id, usuario.codigo)
    return conversacion


def crear_mensaje(db: Session, conversacion_id: int, datos: MensajeCreate, usuario: Usuario):
    conversacion = obtener_conversacion_autorizada(db, conversacion_id, usuario)
    if datos.diagrama_id is not None:
        diagrama = db.query(Diagrama).filter(
            Diagrama.id == datos.diagrama_id,
            Diagrama.id_proyecto == conversacion.proyecto_id,
        ).first()
        if diagrama is None:
            raise HTTPException(404, "El diagrama no pertenece al proyecto")
    nombre = " ".join(parte for parte in (usuario.nombres, usuario.apellidos) if parte).strip()
    mensaje = Mensaje(
        conversacion_id=conversacion.id, diagrama_id=datos.diagrama_id,
        rol="user", autor_codigo=usuario.codigo, autor_nombre=nombre or usuario.email,
        texto=datos.texto,
    )
    try:
        db.add(mensaje)
        db.commit()
        db.refresh(mensaje)
        return mensaje
    except Exception:
        db.rollback()
        raise


def listar_mensajes(
    db: Session, conversacion_id: int, usuario: Usuario,
    limite: int = 50, antes_de: int | None = None,
    *, diagrama_id: int | None = None, filtrar_diagrama: bool = False,
):
    obtener_conversacion_autorizada(db, conversacion_id, usuario)
    query = db.query(Mensaje).filter(Mensaje.conversacion_id == conversacion_id)
    if filtrar_diagrama:
        query = query.filter(Mensaje.diagrama_id == diagrama_id)
    if antes_de is not None:
        query = query.filter(Mensaje.id < antes_de)
    registros = query.order_by(Mensaje.id.desc()).limit(limite + 1).all()
    pagina = registros[:limite]
    siguiente = pagina[-1].id if len(registros) > limite and pagina else None
    return {"mensajes": list(reversed(pagina)), "siguiente_antes_de": siguiente}
