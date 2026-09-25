from datetime import datetime

from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.database import get_db
from app.models.diagrama import Diagrama
from app.models.usuario import Usuario
from app.schemas.diagrama import DiagramaResponse
from app.security.auth_dependencies import get_current_user
from app.services.diagrama import (
    guardar_version_automatica,
    normalizar_contenido,
    obtener_diagrama,
)
from app.services.proyecto import obtener_proyecto, usuario_tiene_permiso
from app.services.uml_validator import validate_uml_relations
from app.services.xmi_exporter import diagram_content_to_xmi
from app.services.xmi_importer import parse_xmi_to_diagram_content


router = APIRouter(tags=["Importar / Exportar"])


def verificar_permiso_proyecto(
    db: Session,
    proyecto_id: int,
    usuario_codigo: str,
    permiso: str,
):
    if not usuario_tiene_permiso(db, proyecto_id, usuario_codigo, permiso):
        raise HTTPException(status_code=403, detail="No tienes permiso para realizar esta accion")


async def leer_xmi_upload(file: UploadFile):
    filename = (file.filename or "").lower()

    if not filename.endswith(".xmi") and not filename.endswith(".xml"):
        raise HTTPException(status_code=400, detail="El archivo debe ser .xmi o .xml")

    content = await file.read()

    if not content:
        raise HTTPException(status_code=400, detail="El archivo XMI esta vacio")

    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("latin-1")


def guardar_importacion_en_diagrama(
    db: Session,
    diagrama: Diagrama,
    contenido: dict,
    autor_codigo: str,
):
    contenido = normalizar_contenido(contenido)
    error = validate_uml_relations(contenido)

    if error:
        raise HTTPException(status_code=400, detail=error)

    diagrama.contenido = contenido
    flag_modified(diagrama, "contenido")
    diagrama.version += 1
    diagrama.actualizado_en = datetime.utcnow()

    guardar_version_automatica(
        db=db,
        diagrama=diagrama,
        autor_codigo=autor_codigo,
        tipo="import_xmi",
        titulo="Importacion XMI",
        descripcion="Checkpoint automatico creado al importar un archivo XMI.",
        forzar=True,
    )

    db.commit()
    db.refresh(diagrama)
    return diagrama


@router.post(
    "/proyectos/{proyecto_id}/diagramas/import/xmi",
    response_model=DiagramaResponse,
)
async def importar_xmi_creando_diagrama(
    proyecto_id: int,
    file: UploadFile = File(...),
    nombre: str = Form(default="Diagrama importado"),
    db: Session = Depends(get_db),
    usuario_actual: Usuario = Depends(get_current_user),
):
    proyecto = obtener_proyecto(db, proyecto_id)

    if proyecto is None:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    verificar_permiso_proyecto(db, proyecto_id, usuario_actual.codigo, "crear_diagrama")
    xmi_text = await leer_xmi_upload(file)
    contenido = normalizar_contenido(parse_xmi_to_diagram_content(xmi_text))
    error = validate_uml_relations(contenido)

    if error:
        raise HTTPException(status_code=400, detail=error)

    diagrama = Diagrama(
        id_proyecto=proyecto_id,
        nombre=nombre,
        contenido=contenido,
        version=1,
    )

    db.add(diagrama)
    db.commit()
    db.refresh(diagrama)

    guardar_version_automatica(
        db=db,
        diagrama=diagrama,
        autor_codigo=usuario_actual.codigo,
        tipo="import_xmi",
        titulo="Importacion XMI",
        descripcion="Checkpoint automatico creado al importar un archivo XMI.",
        forzar=True,
    )
    db.commit()
    db.refresh(diagrama)

    return diagrama


@router.post("/diagramas/{diagrama_id}/import/xmi", response_model=DiagramaResponse)
async def importar_xmi_en_diagrama_existente(
    diagrama_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    usuario_actual: Usuario = Depends(get_current_user),
):
    diagrama = obtener_diagrama(db, diagrama_id)

    if diagrama is None:
        raise HTTPException(status_code=404, detail="Diagrama no encontrado")

    verificar_permiso_proyecto(db, diagrama.id_proyecto, usuario_actual.codigo, "editar_diagrama")
    xmi_text = await leer_xmi_upload(file)
    contenido = parse_xmi_to_diagram_content(xmi_text)

    return guardar_importacion_en_diagrama(
        db=db,
        diagrama=diagrama,
        contenido=contenido,
        autor_codigo=usuario_actual.codigo,
    )


@router.get("/diagramas/{diagrama_id}/export/xmi")
def exportar_xmi(
    diagrama_id: int,
    profile: Literal["standard", "enterprise_architect"] = Query(
        default="enterprise_architect"
    ),
    db: Session = Depends(get_db),
    usuario_actual: Usuario = Depends(get_current_user),
):
    diagrama = obtener_diagrama(db, diagrama_id)

    if diagrama is None:
        raise HTTPException(status_code=404, detail="Diagrama no encontrado")

    verificar_permiso_proyecto(db, diagrama.id_proyecto, usuario_actual.codigo, "ver_diagrama")

    xmi_bytes = diagram_content_to_xmi(
        contenido=normalizar_contenido(diagrama.contenido),
        nombre=diagrama.nombre,
        profile=profile,
    )

    profile_suffix = "_EA" if profile == "enterprise_architect" else ""
    filename = f"{diagrama.nombre.replace(' ', '_')}{profile_suffix}.xmi"

    return Response(
        content=xmi_bytes,
        media_type="application/xml",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
