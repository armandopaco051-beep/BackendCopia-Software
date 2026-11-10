"""Deriva claves en el JSON del diagrama; no ejecuta DDL sobre la base de datos."""
from copy import deepcopy
import re


PK_FLAGS = ("primaryKey", "isPrimaryKey", "isPk", "primary_key", "es_pk", "pk")
FK_FLAGS = ("foreignKey", "isForeignKey", "isFk", "foreign_key", "es_fk", "fk")
MANAGED = "_relationshipKey"


def primary_keys(node):
    return [a for a in (node.get("data") or {}).get("attributes", []) if isinstance(a, dict)
            and (any(a.get(k) is True for k in PK_FLAGS)
                 or (str(a.get("name", "")).lower() == "id" and not any(a.get(k) is False for k in PK_FLAGS)))]


def slug(value):
    return re.sub(r"\W+", "_", str(value).strip().lower()).strip("_")


def synchronize_relationship_keys(content):
    if not isinstance(content, dict):
        return
    nodes = content.get("nodes", [])
    edges = content.get("edges", [])
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return
    by_id = {str(n.get("id")): n for n in nodes if isinstance(n, dict)}
    # Reconstruir a partir de los atributos originales evita claves huérfanas al
    # borrar relaciones o cambiar extremos, tipos, nombres o multiplicidades.
    for node in by_id.values():
        data = node.setdefault("data", {})
        restored = []
        for attr in data.get("attributes", []):
            if not isinstance(attr, dict):
                continue
            managed = attr.get(MANAGED)
            if not isinstance(managed, dict):
                restored.append(attr)
            elif isinstance(managed.get("original"), dict):
                restored.append(deepcopy(managed["original"]))
        data["attributes"] = restored

    def endpoints(edge):
        data = edge.get("data") or {}
        return (by_id.get(str(edge.get("source") or data.get("sourceClassId"))),
                by_id.get(str(edge.get("target") or data.get("targetClassId"))))

    def attach(owner, parent, pk, edge, *, is_pk=False, nullable=False, name=None, role="", unique=False, adopt=False):
        attributes = owner.setdefault("data", {}).setdefault("attributes", [])
        parent_name = str((parent.get("data") or {}).get("name") or "referencia")
        pk_name = str(pk.get("name") or "id")
        proposed = name or (f"id_{slug(parent_name)}" if pk_name.lower() in {"id", "codigo", "pk"} else f"{slug(parent_name)}_{pk_name}")
        ref = {"nodeId": str(parent["id"]), "attribute": pk_name}
        aliases = {proposed.casefold()}
        if adopt:
            aliases |= {f"{parent_name}_{pk_name}".casefold(), f"{pk_name}_{parent_name}".casefold()}
        candidate = next((a for a in attributes if str(a.get("name", "")).casefold() in aliases), None)
        if candidate and MANAGED in candidate:
            if candidate[MANAGED].get("reference") == ref and candidate[MANAGED].get("role") == role:
                changed = candidate.get("type") != (pk.get("type") or "BIGINT")
                candidate["type"] = pk.get("type") or "BIGINT"
                return changed
            candidate = None
            proposed += "_" + slug(role or str(edge.get("id", "ref")))
        elif candidate and not is_pk and any(candidate.get(k) is True for k in PK_FLAGS):
            # Una FK normal nunca convierte la PK propia del lado N en otra cosa.
            candidate = None
            proposed += "_fk"
        if candidate is None:
            base, suffix = proposed, 2
            while any(str(a.get("name", "")).casefold() == proposed.casefold() for a in attributes):
                proposed = f"{base}_{suffix}"
                suffix += 1
            candidate = {"name": proposed}
            attributes.append(candidate)
            original = None
        else:
            # Reconoce claves compuestas de asociación creadas por versiones
            # anteriores, que no tenían metadatos de procedencia.
            legacy = adopt and any(candidate.get(k) is True for k in PK_FLAGS) and any(candidate.get(k) is True for k in FK_FLAGS)
            original = None if legacy else deepcopy(candidate)
        candidate.update(type=pk.get("type") or "BIGINT", nullable=nullable,
                         references=ref, primaryKey=is_pk, isPrimaryKey=is_pk,
                         foreignKey=True, isForeignKey=True)
        for flag in PK_FLAGS:
            if flag in candidate:
                candidate[flag] = is_pk
        for flag in FK_FLAGS:
            if flag in candidate:
                candidate[flag] = True
        if unique:
            candidate["unique"] = True
        candidate[MANAGED] = {"edgeId": str(edge.get("id", "")), "reference": ref, "role": role, "original": original}
        return True

    # El generador Spring Boot del proyecto usa JOINED. SINGLE_TABLE y
    # TABLE_PER_CLASS explícitos no provocan copia de PK entre tablas.
    for _ in range(max(1, len(nodes))):
        changed = False
        for edge in edges:
            data = edge.get("data") or {}
            if data.get("relationType") != "generalization" or str(data.get("inheritanceStrategy", "JOINED")).upper() != "JOINED":
                continue
            child, parent = endpoints(edge)
            if child is None or parent is None:
                continue
            parent_pks, child_pks = primary_keys(parent), primary_keys(child)
            if child_pks and len(child_pks) != len(parent_pks):
                continue  # No inventar una transformación de PK compuestas incompatible.
            for i, pk in enumerate(parent_pks):
                name = child_pks[i].get("name") if child_pks else pk.get("name")
                changed |= attach(child, parent, pk, edge, is_pk=True, name=name, role="inheritance")
        if not changed:
            break

    for edge in edges:
        data = edge.get("data") or {}
        if data.get("relationType") != "associationClass":
            continue
        source, target = endpoints(edge)
        middle = by_id.get(str(data.get("associationClassId")))
        if source is None or target is None or middle is None:
            continue
        for attr in middle.setdefault("data", {}).setdefault("attributes", []):
            if isinstance(attr, dict) and any(attr.get(k) is True for k in PK_FLAGS) and not any(attr.get(k) is True for k in FK_FLAGS):
                original = deepcopy(attr)
                for flag in PK_FLAGS:
                    if flag in attr:
                        attr[flag] = False
                attr[MANAGED] = {"edgeId": str(edge.get("id", "")), "role": "association-own-key", "original": original}
        for role, parent in (("source", source), ("target", target)):
            for pk in primary_keys(parent):
                name = None
                if source is target:
                    name = f"{slug(parent['data'].get('name'))}_{role}_{pk['name']}"
                attach(middle, parent, pk, edge, is_pk=True, role=role, name=name, adopt=True)

    one, many = {"1", "0..1"}, {"0..*", "1..*"}
    for edge in edges:
        data = edge.get("data") or {}
        if data.get("relationType") not in {"association", "aggregation", "composition"}:
            continue
        source, target = endpoints(edge)
        if source is None or target is None:
            continue
        sc, tc = data.get("sourceCardinality"), data.get("targetCardinality")
        if sc in one and tc in many:
            parent, child, cardinality = source, target, sc
        elif tc in one and sc in many:
            parent, child, cardinality = target, source, tc
        else:
            # 1:1 requiere elegir el dueño de la FK; N:M requiere una tabla
            # puente. No se coloca una FK arbitraria en un extremo.
            continue
        for pk in primary_keys(parent):
            attach(child, parent, pk, edge, nullable=cardinality == "0..1", role="many")
