from copy import deepcopy
import hashlib
import json
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.orm import Session

from app.models.diagrama import Diagrama
from app.models.proyecto import Proyecto
from app.models.usuario import Usuario
from app.models.version_historial import VersionHistorial
from app.schemas.diagrama import (
    ClaseCreate,
    ClaseMove,
    ClaseUpdate,
    DiagramaCreate,
    DiagramaUpdate,
    RelacionCreate,
    RelacionUpdate,
)
from app.services.uml_validator import validate_uml_relations
from app.services.relationship_keys import synchronize_relationship_keys


def contenido_inicial():
    return {
        "nodes": [],
        "edges": [],
    }


VERSION_CHECKPOINT_HOURS = 24


def calcular_hash_contenido(contenido: dict):
    contenido_normalizado = json.dumps(
        contenido,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    return hashlib.sha256(contenido_normalizado.encode("utf-8")).hexdigest()


def obtener_ultima_version(db: Session, diagrama_id: int):
    return (
        db.query(VersionHistorial)
        .filter(VersionHistorial.diagrama_id == diagrama_id)
        .order_by(VersionHistorial.fecha.desc())
        .first()
    )


def debe_crear_version_automatica(db: Session, diagrama: Diagrama):
    ultima_version = obtener_ultima_version(db, diagrama.id)
    contenido_hash = calcular_hash_contenido(normalizar_contenido(diagrama.contenido))

    if ultima_version is None:
        return True, contenido_hash

    ultima_version_hash = ultima_version.contenido_hash or calcular_hash_contenido(
        normalizar_contenido(ultima_version.contenido)
    )

    if ultima_version_hash == contenido_hash:
        return False, contenido_hash

    limite_tiempo = datetime.utcnow() - timedelta(hours=VERSION_CHECKPOINT_HOURS)

    if ultima_version.fecha and ultima_version.fecha > limite_tiempo:
        return False, contenido_hash

    return True, contenido_hash


def guardar_version_automatica(
    db: Session,
    diagrama: Diagrama,
    autor_codigo: str | None,
    tipo: str = "auto",
    titulo: str | None = None,
    descripcion: str | None = None,
    forzar: bool = False,
):
    if autor_codigo is None:
        return

    autor = db.query(Usuario).filter(Usuario.codigo == autor_codigo).first()

    if autor is None:
        return

    contenido = normalizar_contenido(diagrama.contenido)
    contenido_hash = calcular_hash_contenido(contenido)

    if not forzar:
        debe_crear, contenido_hash = debe_crear_version_automatica(db, diagrama)

        if not debe_crear:
            return

    version = VersionHistorial(
        diagrama_id=diagrama.id,
        autor_id=autor_codigo,
        contenido=deepcopy(contenido),
        version=diagrama.version,
        titulo=titulo or f"Version {diagrama.version}",
        descripcion=descripcion,
        tipo=tipo,
        contenido_hash=contenido_hash,
    )

    db.add(version)


def sincronizar_clases_asociacion(contenido: dict):
    # Nombre conservado para compatibilidad con el flujo existente.
    synchronize_relationship_keys(contenido)


def normalizar_contenido(contenido: dict | None):
    if not contenido:
        return contenido_inicial()

    nuevo_contenido = deepcopy(contenido)
    nuevo_contenido.setdefault("nodes", [])
    nuevo_contenido.setdefault("edges", [])
    sincronizar_clases_asociacion(nuevo_contenido)
    return nuevo_contenido


def crear_diagrama(db: Session, datos: DiagramaCreate):
    proyecto = db.query(Proyecto).filter(Proyecto.id == datos.id_proyecto).first()

    if proyecto is None:
        return None, "PROYECTO_NO_EXISTE"

    contenido = normalizar_contenido(datos.contenido)
    synchronize_relationship_keys(contenido)
    error = validate_uml_relations(contenido)

    if error:
        return None, error

    diagrama = Diagrama(
        id_proyecto=datos.id_proyecto,
        nombre=datos.nombre,
        contenido=contenido,
        version=1,
    )

    db.add(diagrama)
    db.commit()
    db.refresh(diagrama)

    return diagrama, None


def listar_diagramas(db: Session):
    return db.query(Diagrama).order_by(Diagrama.id.desc()).all()


def listar_diagramas_por_proyecto(db: Session, id_proyecto: int):
    return (
        db.query(Diagrama)
        .filter(Diagrama.id_proyecto == id_proyecto)
        .order_by(Diagrama.id.desc())
        .all()
    )


def obtener_diagrama(db: Session, diagrama_id: int):
    return db.query(Diagrama).filter(Diagrama.id == diagrama_id).first()


def listar_versiones_diagrama(db: Session, diagrama_id: int):
    return (
        db.query(VersionHistorial)
        .filter(VersionHistorial.diagrama_id == diagrama_id)
        .order_by(VersionHistorial.fecha.desc())
        .all()
    )


def restaurar_version_diagrama(
    db: Session,
    diagrama_id: int,
    version_id: int,
    autor_codigo: str | None = None,
):
    diagrama = obtener_diagrama(db, diagrama_id)

    if diagrama is None:
        return None, "DIAGRAMA_NO_EXISTE"

    version = (
        db.query(VersionHistorial)
        .filter(
            VersionHistorial.id == version_id,
            VersionHistorial.diagrama_id == diagrama_id,
        )
        .first()
    )

    if version is None:
        return None, "VERSION_NO_EXISTE"

    guardar_version_automatica(
        db=db,
        diagrama=diagrama,
        autor_codigo=autor_codigo,
        tipo="restore_backup",
        titulo=f"Respaldo antes de restaurar v{version.version}",
        descripcion="Checkpoint automatico creado antes de restaurar una version anterior.",
        forzar=True,
    )

    diagrama.contenido = normalizar_contenido(deepcopy(version.contenido))
    flag_modified(diagrama, "contenido")
    diagrama.version += 1
    diagrama.actualizado_en = datetime.utcnow()

    db.commit()
    db.refresh(diagrama)

    return diagrama, None


def actualizar_diagrama(db: Session, diagrama_id: int, datos: DiagramaUpdate):
    diagrama = obtener_diagrama(db, diagrama_id)

    if diagrama is None:
        return None, "DIAGRAMA_NO_EXISTE"

    if datos.nombre is not None:
        diagrama.nombre = datos.nombre

    if datos.contenido is not None:
        contenido = normalizar_contenido(datos.contenido)
        synchronize_relationship_keys(contenido)
        error = validate_uml_relations(contenido)

        if error:
            return None, error

        diagrama.contenido = contenido
        flag_modified(diagrama, "contenido")

    diagrama.version += 1
    diagrama.actualizado_en = datetime.utcnow()

    guardar_version_automatica(
        db=db,
        diagrama=diagrama,
        autor_codigo=datos.autor_codigo,
    )

    db.commit()
    db.refresh(diagrama)

    return diagrama, None


def eliminar_diagrama(db: Session, diagrama_id: int):
    diagrama = obtener_diagrama(db, diagrama_id)

    if diagrama is None:
        return None

    db.delete(diagrama)
    db.commit()

    return diagrama


def buscar_indice_clase(contenido: dict, clase_id: str):
    target_id = str(clase_id).strip()
    for index, node in enumerate(contenido.get("nodes", [])):
        if str(node.get("id", "")).strip() == target_id:
            return index

    return None


def agregar_clase(db: Session, diagrama_id: int, datos: ClaseCreate):
    diagrama = obtener_diagrama(db, diagrama_id)

    if diagrama is None:
        return None, "DIAGRAMA_NO_EXISTE"

    contenido = normalizar_contenido(diagrama.contenido)
    clase_id = datos.id or f"class-{uuid4().hex[:8]}"
    datos.id = clase_id

    if buscar_indice_clase(contenido, clase_id) is not None:
        return None, "CLASE_YA_EXISTE"

    nueva_clase = {
        "id": clase_id,
        "type": "classNode",
        "position": {
            "x": datos.x,
            "y": datos.y,
        },
        "data": {
            "name": datos.name,
            "kind": datos.kind,
            "attributes": datos.attributes,
            "methods": datos.methods,
            "templateParameters": datos.templateParameters,
        },
    }

    contenido["nodes"].append(nueva_clase)
    synchronize_relationship_keys(contenido)
    error = validate_uml_relations(contenido)

    if error:
        return None, error

    diagrama.contenido = contenido
    flag_modified(diagrama, "contenido")
    diagrama.version += 1
    diagrama.actualizado_en = datetime.utcnow()

    guardar_version_automatica(
        db=db,
        diagrama=diagrama,
        autor_codigo=datos.autor_codigo,
    )

    db.commit()
    db.refresh(diagrama)

    return diagrama, None


def mover_clase(db: Session, diagrama_id: int, clase_id: str, datos: ClaseMove):
    diagrama = obtener_diagrama(db, diagrama_id)

    if diagrama is None:
        return None, "DIAGRAMA_NO_EXISTE"

    contenido = normalizar_contenido(diagrama.contenido)
    index = buscar_indice_clase(contenido, clase_id)

    if index is None:
        return None, "CLASE_NO_EXISTE"

    contenido["nodes"][index]["position"] = {
        "x": datos.x,
        "y": datos.y,
    }

    synchronize_relationship_keys(contenido)
    error = validate_uml_relations(contenido)

    if error:
        return None, error

    diagrama.contenido = contenido
    flag_modified(diagrama, "contenido")
    diagrama.version += 1
    diagrama.actualizado_en = datetime.utcnow()

    guardar_version_automatica(
        db=db,
        diagrama=diagrama,
        autor_codigo=datos.autor_codigo,
    )

    db.commit()
    db.refresh(diagrama)

    return diagrama, None


def editar_clase(db: Session, diagrama_id: int, clase_id: str, datos: ClaseUpdate):
    diagrama = obtener_diagrama(db, diagrama_id)

    if diagrama is None:
        return None, "DIAGRAMA_NO_EXISTE"

    contenido = normalizar_contenido(diagrama.contenido)
    index = buscar_indice_clase(contenido, clase_id)

    if index is None:
        return None, "CLASE_NO_EXISTE"

    data = contenido["nodes"][index].setdefault("data", {})

    if datos.name is not None:
        data["name"] = datos.name

    if datos.attributes is not None:
        data["attributes"] = datos.attributes

    if datos.methods is not None:
        data["methods"] = datos.methods

    if datos.kind is not None:
        data["kind"] = datos.kind

    if datos.templateParameters is not None:
        data["templateParameters"] = datos.templateParameters

    synchronize_relationship_keys(contenido)
    error = validate_uml_relations(contenido)

    if error:
        return None, error

    diagrama.contenido = contenido
    flag_modified(diagrama, "contenido")
    diagrama.version += 1
    diagrama.actualizado_en = datetime.utcnow()

    guardar_version_automatica(
        db=db,
        diagrama=diagrama,
        autor_codigo=datos.autor_codigo,
    )

    db.commit()
    db.refresh(diagrama)

    return diagrama, None


def eliminar_clase(db: Session, diagrama_id: int, clase_id: str, autor_codigo: str | None = None):
    diagrama = obtener_diagrama(db, diagrama_id)

    if diagrama is None:
        return None, "DIAGRAMA_NO_EXISTE"

    contenido = normalizar_contenido(diagrama.contenido)
    index = buscar_indice_clase(contenido, clase_id)

    if index is None:
        return None, "CLASE_NO_EXISTE"

    contenido["nodes"].pop(index)
    contenido["edges"] = [
        edge
        for edge in contenido.get("edges", [])
        if (
            edge.get("source") != clase_id
            and edge.get("target") != clase_id
            and (edge.get("data") or {}).get("associationClassId") != clase_id
        )
    ]

    synchronize_relationship_keys(contenido)
    error = validate_uml_relations(contenido)

    if error:
        return None, error

    diagrama.contenido = contenido
    flag_modified(diagrama, "contenido")
    diagrama.version += 1
    diagrama.actualizado_en = datetime.utcnow()

    guardar_version_automatica(
        db=db,
        diagrama=diagrama,
        autor_codigo=autor_codigo,
        tipo="auto",
        titulo=f"Version {diagrama.version}",
        descripcion="Checkpoint automatico despues de eliminar una clase.",
        forzar=True,
    )

    db.commit()
    db.refresh(diagrama)

    return diagrama, None


def buscar_indice_relacion(contenido: dict, relacion_id: str):
    for index, edge in enumerate(contenido.get("edges", [])):
        if edge.get("id") == relacion_id:
            return index

    return None


def agregar_relacion(db: Session, diagrama_id: int, datos: RelacionCreate):
    diagrama = obtener_diagrama(db, diagrama_id)

    if diagrama is None:
        return None, "DIAGRAMA_NO_EXISTE"

    contenido = normalizar_contenido(diagrama.contenido)
    relacion_id = datos.id or f"rel-{uuid4().hex[:8]}"

    if buscar_indice_relacion(contenido, relacion_id) is not None:
        return None, "RELACION_YA_EXISTE"

    data = deepcopy(datos.data)
    data.setdefault("sourceClassId", datos.source)
    data.setdefault("targetClassId", datos.target)

    nueva_relacion = {
        "id": relacion_id,
        "source": datos.source,
        "target": datos.target,
        "data": data,
    }

    if datos.type is not None:
        nueva_relacion["type"] = datos.type

    contenido["edges"].append(nueva_relacion)

    synchronize_relationship_keys(contenido)
    error = validate_uml_relations(contenido)

    if error:
        return None, error

    diagrama.contenido = contenido
    flag_modified(diagrama, "contenido")
    diagrama.version += 1
    diagrama.actualizado_en = datetime.utcnow()

    guardar_version_automatica(
        db=db,
        diagrama=diagrama,
        autor_codigo=datos.autor_codigo,
    )

    db.commit()
    db.refresh(diagrama)

    return diagrama, None


def editar_relacion(db: Session, diagrama_id: int, relacion_id: str, datos: RelacionUpdate):
    diagrama = obtener_diagrama(db, diagrama_id)

    if diagrama is None:
        return None, "DIAGRAMA_NO_EXISTE"

    contenido = normalizar_contenido(diagrama.contenido)
    index = buscar_indice_relacion(contenido, relacion_id)

    if index is None:
        return None, "RELACION_NO_EXISTE"

    relacion = deepcopy(contenido["edges"][index])

    if datos.source is not None:
        relacion["source"] = datos.source

    if datos.target is not None:
        relacion["target"] = datos.target

    if datos.type is not None:
        relacion["type"] = datos.type

    if datos.data is not None:
        relacion["data"] = datos.data

    data = relacion.setdefault("data", {})
    data["sourceClassId"] = relacion.get("source")
    data["targetClassId"] = relacion.get("target")

    contenido["edges"][index] = relacion

    synchronize_relationship_keys(contenido)
    error = validate_uml_relations(contenido)

    if error:
        return None, error

    diagrama.contenido = contenido
    flag_modified(diagrama, "contenido")
    diagrama.version += 1
    diagrama.actualizado_en = datetime.utcnow()

    guardar_version_automatica(
        db=db,
        diagrama=diagrama,
        autor_codigo=datos.autor_codigo,
    )

    db.commit()
    db.refresh(diagrama)

    return diagrama, None


def eliminar_relacion(db: Session, diagrama_id: int, relacion_id: str, autor_codigo: str | None = None):
    diagrama = obtener_diagrama(db, diagrama_id)

    if diagrama is None:
        return None, "DIAGRAMA_NO_EXISTE"

    contenido = normalizar_contenido(diagrama.contenido)
    index = buscar_indice_relacion(contenido, relacion_id)

    if index is None:
        return None, "RELACION_NO_EXISTE"

    contenido["edges"].pop(index)

    synchronize_relationship_keys(contenido)
    error = validate_uml_relations(contenido)

    if error:
        return None, error

    diagrama.contenido = contenido
    flag_modified(diagrama, "contenido")
    diagrama.version += 1
    diagrama.actualizado_en = datetime.utcnow()

    guardar_version_automatica(
        db=db,
        diagrama=diagrama,
        autor_codigo=autor_codigo,
        tipo="auto",
        titulo=f"Version {diagrama.version}",
        descripcion="Checkpoint automatico despues de eliminar una relacion.",
        forzar=True,
    )

    db.commit()
    db.refresh(diagrama)

    return diagrama, None
