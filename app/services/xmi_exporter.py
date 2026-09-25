from __future__ import annotations

import xml.etree.ElementTree as ET
import uuid
from typing import Any


XMI_NS = "http://www.omg.org/spec/XMI/20131001"
UML_NS = "http://www.omg.org/spec/UML/20131001"
EA_XMI_NS = "http://schema.omg.org/spec/XMI/2.1"
EA_UML_NS = "http://schema.omg.org/spec/UML/2.1"
STANDARD_PROFILE = "standard"
ENTERPRISE_ARCHITECT_PROFILE = "enterprise_architect"
DEFAULT_NODE_WIDTH = 245
DEFAULT_NODE_HEIGHT = 180
EA_LAYOUT_MAX_WIDTH = 960
EA_LAYOUT_MAX_HEIGHT = 720
EA_LAYOUT_MARGIN = 40

ET.register_namespace("xmi", XMI_NS)
ET.register_namespace("uml", UML_NS)


def safe_id(value: str):
    return (
        str(value)
        .replace(" ", "_")
        .replace("-", "_")
        .replace(".", "_")
        .replace(":", "_")
    )


def xmi_attr(name: str):
    return f"{{{XMI_NS}}}{name}"


def get_node_name(node: dict[str, Any]):
    data = node.get("data") or {}
    return data.get("name") or node.get("id") or "Clase"


def get_relation_type(edge: dict[str, Any]):
    data = edge.get("data") or {}
    return data.get("relationType") or edge.get("type") or "association"


def numeric_value(value: Any, default: float):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def get_node_size(node: dict[str, Any]):
    data = node.get("data") or {}
    style = node.get("style") or {}
    measured = node.get("measured") or {}
    attribute_count = max(len(data.get("attributes") or []), 1)
    method_count = max(len(data.get("methods") or []), 1)
    content_height = 46 + 40 + attribute_count * 22 + method_count * 22 + 12
    width = numeric_value(
        style.get("width", node.get("width", measured.get("width"))),
        DEFAULT_NODE_WIDTH,
    )
    height = numeric_value(
        style.get("height", node.get("height", measured.get("height"))),
        max(DEFAULT_NODE_HEIGHT, content_height),
    )
    return max(width, DEFAULT_NODE_WIDTH), max(height, DEFAULT_NODE_HEIGHT, content_height)


def get_node_position(node: dict[str, Any]):
    position = node.get("position") or {}
    return numeric_value(position.get("x"), 0), numeric_value(position.get("y"), 0)


def integer_coordinate(value: float):
    return str(int(round(value)))


def geometry_value(left: float, top: float, width: float, height: float):
    return (
        f"Left={integer_coordinate(left)};"
        f"Top={integer_coordinate(top)};"
        f"Right={integer_coordinate(left + width)};"
        f"Bottom={integer_coordinate(top + height)};"
    )


def normalized_diagram_positions(nodes: list[dict[str, Any]]):
    if not nodes:
        return {}, 1.0

    raw_positions = {str(node.get("id")): get_node_position(node) for node in nodes}
    min_x = min(position[0] for position in raw_positions.values())
    min_y = min(position[1] for position in raw_positions.values())
    max_right = max(
        raw_positions[str(node.get("id"))][0] + get_node_size(node)[0]
        for node in nodes
    )
    max_bottom = max(
        raw_positions[str(node.get("id"))][1] + get_node_size(node)[1]
        for node in nodes
    )
    content_width = max(max_right - min_x, 1)
    content_height = max(max_bottom - min_y, 1)
    scale = min(
        1.0,
        EA_LAYOUT_MAX_WIDTH / content_width,
        EA_LAYOUT_MAX_HEIGHT / content_height,
    )
    normalized = {
        node_id: (
            EA_LAYOUT_MARGIN + (position[0] - min_x) * scale,
            EA_LAYOUT_MARGIN + (position[1] - min_y) * scale,
        )
        for node_id, position in raw_positions.items()
    }
    return normalized, scale


def ea_guid(prefix: str, value: str):
    generated = uuid.uuid5(uuid.NAMESPACE_URL, f"drawschema:{prefix}:{value}")
    return f"{prefix}_{str(generated).replace('-', '_').upper()}"


def diagram_object_id(value: str):
    return uuid.uuid5(uuid.NAMESPACE_URL, f"drawschema:diagram-object:{value}").hex[:8].upper()


def feature_id(node_id: str, feature_type: str, index: int):
    return ea_guid("EAID", f"{node_id}:{feature_type}:{index}")


def ea_braced_guid(value: str):
    return f"{{{value.removeprefix('EAID_').replace('_', '-')}}}"


def normalize_parameter(parameter: Any, index: int):
    if isinstance(parameter, dict):
        return {
            "name": str(parameter.get("name") or parameter.get("nombre") or f"parametro{index + 1}"),
            "type": str(parameter.get("type") or parameter.get("tipo") or "String"),
        }

    return {
        "name": str(parameter or f"parametro{index + 1}"),
        "type": "String",
    }


def boolean_value(value: Any, default: bool = False):
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "si"}
    return bool(value)


def uml_visibility(value: Any, default: str = "private"):
    normalized = str(value or default).strip().lower()
    return normalized if normalized in {"public", "private", "protected", "package"} else default


def ea_visibility(value: Any, default: str = "Private"):
    return uml_visibility(value, default.lower()).capitalize()


def attribute_type(attribute: dict[str, Any]):
    return str(attribute.get("type") or attribute.get("tipo") or "String").strip() or "String"


def method_return_type(method: dict[str, Any]):
    return str(method.get("returnType") or method.get("tipoRetorno") or "void").strip() or "void"


def collect_used_types(contenido: dict[str, Any]):
    used_types: dict[str, str] = {}
    for node in contenido.get("nodes", []):
        data = node.get("data") or {}
        for attribute in data.get("attributes") or []:
            type_name = attribute_type(attribute)
            used_types.setdefault(type_name.casefold(), type_name)
        for method in data.get("methods") or []:
            return_type = method_return_type(method)
            if return_type.casefold() != "void":
                used_types.setdefault(return_type.casefold(), return_type)
            for index, parameter in enumerate(method.get("parameters") or []):
                normalized = normalize_parameter(parameter, index)
                type_name = normalized["type"].strip() or "String"
                used_types.setdefault(type_name.casefold(), type_name)
    return list(used_types.values())


def primitive_type_id(type_name: str):
    return f"EAJava_{safe_id(type_name)}"


def add_type_reference(element: ET.Element, type_name: str, type_ids: dict[str, str] | None):
    if type_ids is None:
        element.set("type", type_name)
        return
    ET.SubElement(element, "type", {xmi_attr("idref"): type_ids[type_name.casefold()]})


def create_class_element(
    model: ET.Element,
    node: dict[str, Any],
    force_association_class: bool = False,
    type_ids: dict[str, str] | None = None,
):
    data = node.get("data") or {}
    node_id = str(node.get("id"))
    kind = data.get("kind") or "class"

    if force_association_class:
        element_type = "uml:AssociationClass"
    else:
        element_type = "uml:Interface" if kind == "interface" else "uml:Class"

    element_attributes = {
        xmi_attr("type"): element_type,
        xmi_attr("id"): safe_id(node_id),
        "name": str(get_node_name(node)),
        "visibility": uml_visibility(data.get("visibility"), "public"),
    }
    if kind == "abstractClass":
        element_attributes["isAbstract"] = "true"

    class_element = ET.SubElement(
        model,
        "packagedElement",
        element_attributes,
    )

    for attr_index, attribute in enumerate(data.get("attributes") or []):
        attr_id = feature_id(node_id, "attribute", attr_index + 1)
        owned_attribute = ET.SubElement(
            class_element,
            "ownedAttribute",
            {
                xmi_attr("type"): "uml:Property",
                xmi_attr("id"): attr_id,
                "name": str(attribute.get("name") or f"atributo{attr_index + 1}"),
                "visibility": uml_visibility(attribute.get("visibility")),
                "isStatic": str(boolean_value(attribute.get("static"))).lower(),
                "isReadOnly": str(boolean_value(attribute.get("readOnly"))).lower(),
                "isDerived": str(boolean_value(attribute.get("derived"))).lower(),
                "isOrdered": str(boolean_value(attribute.get("ordered"))).lower(),
                "isUnique": str(boolean_value(attribute.get("unique"), True)).lower(),
                "isDerivedUnion": "false",
            },
        )
        nullable = boolean_value(attribute.get("nullable"), True)
        ET.SubElement(
            owned_attribute,
            "lowerValue",
            {
                xmi_attr("type"): "uml:LiteralInteger",
                xmi_attr("id"): f"{attr_id}_lower",
                "value": "0" if nullable else "1",
            },
        )
        ET.SubElement(
            owned_attribute,
            "upperValue",
            {
                xmi_attr("type"): "uml:LiteralInteger",
                xmi_attr("id"): f"{attr_id}_upper",
                "value": "1",
            },
        )
        add_type_reference(owned_attribute, attribute_type(attribute), type_ids)
        default_value = attribute.get("defaultValue", attribute.get("default"))
        if default_value not in {None, ""}:
            ET.SubElement(
                owned_attribute,
                "defaultValue",
                {
                    xmi_attr("type"): "uml:LiteralString",
                    xmi_attr("id"): f"{attr_id}_default",
                    "value": str(default_value),
                },
            )

    for method_index, method in enumerate(data.get("methods") or []):
        method_id = feature_id(node_id, "operation", method_index + 1)
        operation = ET.SubElement(
            class_element,
            "ownedOperation",
            {
                xmi_attr("type"): "uml:Operation",
                xmi_attr("id"): method_id,
                "name": str(method.get("name") or f"metodo{method_index + 1}"),
                "visibility": uml_visibility(method.get("visibility"), "public"),
                "isStatic": str(boolean_value(method.get("static"))).lower(),
                "isAbstract": str(boolean_value(method.get("abstract"))).lower(),
            },
        )

        for param_index, parameter in enumerate(method.get("parameters") or []):
            normalized_parameter = normalize_parameter(parameter, param_index)
            parameter_element = ET.SubElement(
                operation,
                "ownedParameter",
                {
                    xmi_attr("type"): "uml:Parameter",
                    xmi_attr("id"): feature_id(node_id, f"operation-{method_index + 1}-parameter", param_index + 1),
                    "name": normalized_parameter["name"],
                    "direction": "in",
                },
            )
            add_type_reference(
                parameter_element,
                normalized_parameter["type"],
                type_ids,
            )
            if type_ids is not None:
                type_child = parameter_element.find("type")
                if type_child is not None:
                    parameter_element.remove(type_child)
                parameter_element.set("type", type_ids[normalized_parameter["type"].casefold()])

        return_type = method_return_type(method)

        if return_type.casefold() != "void":
            return_parameter = ET.SubElement(
                operation,
                "ownedParameter",
                {
                    xmi_attr("type"): "uml:Parameter",
                    xmi_attr("id"): feature_id(node_id, "return", method_index + 1),
                    "name": "return",
                    "direction": "return",
                },
            )
            add_type_reference(return_parameter, return_type, type_ids)
            if type_ids is not None:
                type_child = return_parameter.find("type")
                if type_child is not None:
                    return_parameter.remove(type_child)
                return_parameter.set("type", type_ids[return_type.casefold()])

    return class_element


def add_generalization(class_elements: dict[str, ET.Element], edge: dict[str, Any]):
    source = str(edge.get("source"))
    target = str(edge.get("target"))
    source_element = class_elements.get(source)

    if source_element is None:
        return

    ET.SubElement(
        source_element,
        "generalization",
        {
            xmi_attr("id"): safe_id(str(edge.get("id") or f"gen_{source}_{target}")),
            "general": safe_id(target),
        },
    )


def cardinality_bounds(cardinality: Any):
    return {
        "1": ("1", "1"),
        "0..1": ("0", "1"),
        "0..*": ("0", "*"),
        "1..*": ("1", "*"),
    }.get(str(cardinality), ("1", "1"))


def add_multiplicity(
    owned_end: ET.Element,
    cardinality: Any,
    end_id: str,
):
    lower, upper = cardinality_bounds(cardinality)
    ET.SubElement(
        owned_end,
        "lowerValue",
        {
            xmi_attr("type"): "uml:LiteralInteger",
            xmi_attr("id"): f"{end_id}_lower",
            "value": lower,
        },
    )
    ET.SubElement(
        owned_end,
        "upperValue",
        {
            xmi_attr("type"): "uml:LiteralUnlimitedNatural",
            xmi_attr("id"): f"{end_id}_upper",
            "value": upper,
        },
    )


def add_binary_association_ends(
    association: ET.Element,
    edge: dict[str, Any],
    association_id: str,
):
    relation_type = get_relation_type(edge)
    data = edge.get("data") or {}
    source = safe_id(str(edge.get("source")))
    target = safe_id(str(edge.get("target")))
    edge_id = safe_id(str(edge.get("id") or f"rel_{source}_{target}"))
    source_end_id = f"{edge_id}_source"
    target_end_id = f"{edge_id}_target"

    source_attrs = {
        xmi_attr("type"): "uml:Property",
        xmi_attr("id"): source_end_id,
        "association": association_id,
        "visibility": "public",
        "aggregation": "none",
    }
    target_attrs = {
        xmi_attr("type"): "uml:Property",
        xmi_attr("id"): target_end_id,
        "association": association_id,
        "visibility": "public",
        "aggregation": "none",
    }

    if data.get("sourceRole"):
        source_attrs["name"] = str(data["sourceRole"])
    if data.get("targetRole"):
        target_attrs["name"] = str(data["targetRole"])

    if relation_type == "composition":
        source_attrs["aggregation"] = "composite"

    if relation_type == "aggregation":
        source_attrs["aggregation"] = "shared"

    source_end = ET.SubElement(association, "ownedEnd", source_attrs)
    target_end = ET.SubElement(association, "ownedEnd", target_attrs)
    ET.SubElement(source_end, "type", {xmi_attr("idref"): source})
    ET.SubElement(target_end, "type", {xmi_attr("idref"): target})
    add_multiplicity(source_end, data.get("sourceCardinality", "1"), source_end_id)
    add_multiplicity(target_end, data.get("targetCardinality", "0..*"), target_end_id)

    existing_member_ends = association.get("memberEnd", "").split()
    association.set(
        "memberEnd",
        " ".join([*existing_member_ends, source_end_id, target_end_id]),
    )
    association.set("navigableOwnedEnd", f"{source_end_id} {target_end_id}")


def add_association(model: ET.Element, edge: dict[str, Any]):
    data = edge.get("data") or {}
    source = safe_id(str(edge.get("source")))
    target = safe_id(str(edge.get("target")))
    relation_id = safe_id(str(edge.get("id") or f"rel_{source}_{target}"))
    association_attributes = {
        xmi_attr("type"): "uml:Association",
        xmi_attr("id"): relation_id,
    }
    if data.get("name"):
        association_attributes["name"] = str(data["name"])

    association = ET.SubElement(model, "packagedElement", association_attributes)
    add_binary_association_ends(association, edge, relation_id)


def add_directed_relation(model: ET.Element, edge: dict[str, Any]):
    relation_type = get_relation_type(edge)
    source = safe_id(str(edge.get("source")))
    target = safe_id(str(edge.get("target")))
    relation_id = safe_id(str(edge.get("id") or f"rel_{source}_{target}"))
    uml_type = "uml:Realization" if relation_type == "realization" else "uml:Dependency"
    attributes = {
        xmi_attr("type"): uml_type,
        xmi_attr("id"): relation_id,
        "client": source,
        "supplier": target,
    }
    if relation_type == "templateBinding":
        attributes["name"] = "templateBinding"

    ET.SubElement(model, "packagedElement", attributes)


def add_association_class(
    class_elements: dict[str, ET.Element],
    edge: dict[str, Any],
):
    data = edge.get("data") or {}
    association_class_id = str(data.get("associationClassId") or "")
    association_class = class_elements.get(association_class_id)
    if association_class is None:
        return

    add_binary_association_ends(
        association_class,
        edge,
        safe_id(association_class_id),
    )
    children = list(association_class)
    owned_ends = [child for child in children if child.tag == "ownedEnd"]
    other_features = [child for child in children if child.tag != "ownedEnd"]
    for child in children:
        association_class.remove(child)
    for owned_end in owned_ends:
        ET.SubElement(
            association_class,
            "memberEnd",
            {xmi_attr("idref"): owned_end.get(xmi_attr("id"), "")},
        )
    for owned_end in owned_ends:
        association_class.append(owned_end)
    for feature in other_features:
        association_class.append(feature)


def exported_relation_id(edge: dict[str, Any]):
    relation_type = get_relation_type(edge)
    source = safe_id(str(edge.get("source")))
    target = safe_id(str(edge.get("target")))

    if relation_type == "generalization":
        return safe_id(str(edge.get("id") or f"gen_{source}_{target}"))
    if relation_type in {"association", "composition", "aggregation"}:
        return safe_id(str(edge.get("id") or f"rel_{source}_{target}"))
    if relation_type in {"realization", "templateBinding"}:
        return safe_id(str(edge.get("id") or f"rel_{source}_{target}"))
    if relation_type == "associationClass":
        return safe_id(str(edge.get("id") or f"rel_{source}_{target}"))
    return None


def node_extension_type(node: dict[str, Any], association_class_ids: set[str]):
    node_id = str(node.get("id"))
    kind = (node.get("data") or {}).get("kind") or "class"
    if node_id in association_class_ids:
        return "uml:Class", "Class", "17"
    if kind == "interface":
        return "uml:Interface", "Interface", "0"
    return "uml:Class", "Class", "0"


def relation_extension_name(edge: dict[str, Any]):
    return {
        "generalization": "Generalization",
        "realization": "Realisation",
        "templateBinding": "Dependency",
    }.get(get_relation_type(edge), "Association")


def add_ea_tag(tags: ET.Element, name: str, value: Any, model_element: str):
    ET.SubElement(
        tags,
        "tag",
        {
            "name": name,
            "value": str(value).lower() if isinstance(value, bool) else str(value),
            "modelElement": model_element,
        },
    )


def add_ea_attribute_metadata(
    attributes_element: ET.Element,
    node_id: str,
    attribute: dict[str, Any],
    index: int,
):
    attr_id = feature_id(node_id, "attribute", index + 1)
    nullable = boolean_value(attribute.get("nullable"), True)
    primary_key = boolean_value(
        attribute.get("primaryKey", attribute.get("isPrimaryKey")),
    )
    foreign_key = boolean_value(
        attribute.get("foreignKey", attribute.get("isForeignKey")),
    )
    metadata = ET.SubElement(
        attributes_element,
        "attribute",
        {
            xmi_attr("idref"): attr_id,
            "name": str(attribute.get("name") or f"atributo{index + 1}"),
            "scope": ea_visibility(attribute.get("visibility")),
        },
    )
    default_value = attribute.get("defaultValue", attribute.get("default"))
    ET.SubElement(metadata, "initial", {"body": str(default_value)}) if default_value not in {None, ""} else ET.SubElement(metadata, "initial")
    ET.SubElement(metadata, "documentation")
    ET.SubElement(metadata, "model", {"ea_localid": str(index + 1), "ea_guid": attr_id})
    ET.SubElement(
        metadata,
        "properties",
        {
            "type": attribute_type(attribute),
            "collection": "false",
            "static": "1" if boolean_value(attribute.get("static")) else "0",
            "duplicates": "0" if boolean_value(attribute.get("unique"), True) else "1",
            "changeability": "frozen" if boolean_value(attribute.get("readOnly")) else "changeable",
        },
    )
    ET.SubElement(metadata, "coords", {"ordered": "1" if boolean_value(attribute.get("ordered")) else "0"})
    ET.SubElement(metadata, "containment", {"containment": "Not Specified", "position": str(index)})
    stereotypes = []
    if primary_key:
        stereotypes.append("PK")
    if foreign_key:
        stereotypes.append("FK")
    ET.SubElement(metadata, "stereotype", {"stereotype": ",".join(stereotypes)}) if stereotypes else ET.SubElement(metadata, "stereotype")
    ET.SubElement(metadata, "bounds", {"lower": "0" if nullable else "1", "upper": "1"})
    ET.SubElement(metadata, "options")
    ET.SubElement(metadata, "style")
    ET.SubElement(metadata, "styleex", {"value": "volatile=0;"})
    tags = ET.SubElement(metadata, "tags")
    add_ea_tag(tags, "nullable", nullable, attr_id)
    if primary_key:
        add_ea_tag(tags, "primaryKey", True, attr_id)
    if foreign_key:
        add_ea_tag(tags, "foreignKey", True, attr_id)
    if boolean_value(attribute.get("unique")):
        add_ea_tag(tags, "unique", True, attr_id)
    ET.SubElement(metadata, "xrefs")


def add_ea_operation_metadata(
    operations_element: ET.Element,
    node_id: str,
    method: dict[str, Any],
    index: int,
):
    method_id = feature_id(node_id, "operation", index + 1)
    return_type = method_return_type(method)
    metadata = ET.SubElement(
        operations_element,
        "operation",
        {
            xmi_attr("idref"): method_id,
            "name": str(method.get("name") or f"metodo{index + 1}"),
            "scope": ea_visibility(method.get("visibility"), "Public"),
        },
    )
    ET.SubElement(metadata, "properties", {"position": str(index)})
    ET.SubElement(metadata, "stereotype")
    ET.SubElement(
        metadata,
        "model",
        {"ea_localid": str(index + 1), "ea_guid": ea_braced_guid(method_id)},
    )
    ET.SubElement(
        metadata,
        "type",
        {
            "type": "" if return_type.casefold() == "void" else return_type,
            "const": "false",
            "static": str(boolean_value(method.get("static"))).lower(),
            "isAbstract": str(boolean_value(method.get("abstract"))).lower(),
            "synchronised": "0",
            "pure": "0",
            "isQuery": "false",
        },
    )
    for child_name in ("behaviour", "code", "style", "styleex", "documentation", "tags"):
        ET.SubElement(metadata, child_name)
    parameters_element = ET.SubElement(metadata, "parameters")

    if return_type.casefold() != "void":
        return_id = feature_id(node_id, "return", index + 1)
        return_parameter = ET.SubElement(
            parameters_element,
            "parameter",
            {xmi_attr("idref"): return_id, "visibility": "public"},
        )
        ET.SubElement(
            return_parameter,
            "properties",
            {
                "pos": "0",
                "type": return_type,
                "const": "false",
                "ea_guid": ea_braced_guid(return_id),
            },
        )
        for child_name in ("style", "styleex", "documentation", "tags", "xrefs"):
            ET.SubElement(return_parameter, child_name)

    for param_index, parameter in enumerate(method.get("parameters") or []):
        normalized = normalize_parameter(parameter, param_index)
        parameter_id = feature_id(node_id, f"operation-{index + 1}-parameter", param_index + 1)
        parameter_element = ET.SubElement(
            parameters_element,
            "parameter",
            {
                xmi_attr("idref"): parameter_id,
                "visibility": "public",
            },
        )
        ET.SubElement(
            parameter_element,
            "properties",
            {
                "pos": str(param_index),
                "type": normalized["type"],
                "const": "false",
                "ea_guid": ea_braced_guid(parameter_id),
            },
        )
        for child_name in ("style", "styleex", "documentation", "tags", "xrefs"):
            ET.SubElement(parameter_element, child_name)
    ET.SubElement(metadata, "xrefs")


def add_ea_elements(
    extension: ET.Element,
    contenido: dict[str, Any],
    package_id: str,
    association_class_ids: set[str],
):
    elements = ET.SubElement(extension, "elements")
    edges = contenido.get("edges") or []
    association_edge_by_class = {
        str((edge.get("data") or {}).get("associationClassId")): edge
        for edge in edges
        if get_relation_type(edge) == "associationClass"
        and (edge.get("data") or {}).get("associationClassId")
    }

    for node_index, node in enumerate(contenido.get("nodes") or [], start=1):
        node_id = str(node.get("id"))
        safe_node_id = safe_id(node_id)
        data = node.get("data") or {}
        uml_type, ea_type, numeric_type = node_extension_type(node, association_class_ids)
        element = ET.SubElement(
            elements,
            "element",
            {
                xmi_attr("idref"): safe_node_id,
                xmi_attr("type"): uml_type,
                "name": str(get_node_name(node)),
                "scope": uml_visibility(data.get("visibility"), "public"),
            },
        )
        ET.SubElement(
            element,
            "model",
            {
                "package": package_id,
                "tpos": "0",
                "ea_localid": str(1000 + node_index),
                "ea_eleType": "element",
            },
        )
        ET.SubElement(
            element,
            "properties",
            {
                "isSpecification": "false",
                "sType": ea_type,
                "nType": numeric_type,
                "scope": uml_visibility(data.get("visibility"), "public"),
                "isRoot": "false",
                "isLeaf": "false",
                "isAbstract": str((data.get("kind") == "abstractClass") or boolean_value(data.get("abstract"))).lower(),
                "isActive": "false",
            },
        )
        ET.SubElement(element, "project", {"author": "DrawSchema", "version": "1.0", "status": "Proposed"})
        ET.SubElement(element, "code", {"gentype": "Java"})
        ET.SubElement(element, "style", {"appearance": "BackColor=-1;BorderColor=-1;BorderWidth=-1;FontColor=-1;BorderStyle=0;"})
        ET.SubElement(element, "tags")
        ET.SubElement(element, "xrefs")
        extended_attributes = {"tagged": "0", "package_name": package_id}
        association_edge = association_edge_by_class.get(node_id)
        if association_edge:
            extended_attributes["conID"] = exported_relation_id(association_edge) or ""
        ET.SubElement(element, "extendedProperties", extended_attributes)

        attributes = data.get("attributes") or []
        if attributes:
            attributes_element = ET.SubElement(element, "attributes")
            for attr_index, attribute in enumerate(attributes):
                add_ea_attribute_metadata(attributes_element, node_id, attribute, attr_index)

        methods = data.get("methods") or []
        if methods:
            operations_element = ET.SubElement(element, "operations")
            for method_index, method in enumerate(methods):
                add_ea_operation_metadata(operations_element, node_id, method, method_index)

        related_edges = [
            edge
            for edge in edges
            if str(edge.get("source")) == node_id or str(edge.get("target")) == node_id
        ]
        if related_edges:
            links = ET.SubElement(element, "links")
            for edge in related_edges:
                relation_id = exported_relation_id(edge)
                if not relation_id:
                    continue
                ET.SubElement(
                    links,
                    relation_extension_name(edge),
                    {
                        xmi_attr("id"): relation_id,
                        "start": safe_id(str(edge.get("source"))),
                        "end": safe_id(str(edge.get("target"))),
                    },
                )
    return elements


def add_ea_connector_end(
    connector: ET.Element,
    tag: str,
    node: dict[str, Any],
    cardinality: Any,
    aggregation: str,
    role_name: Any,
):
    node_id = safe_id(str(node.get("id")))
    data = node.get("data") or {}
    end = ET.SubElement(connector, tag, {xmi_attr("idref"): node_id})
    ET.SubElement(end, "model", {"ea_localid": node_id, "type": "Class", "name": str(get_node_name(node))})
    role_attributes = {"visibility": "Public", "targetScope": "instance"}
    if role_name:
        role_attributes["name"] = str(role_name)
    ET.SubElement(end, "role", role_attributes)
    type_attributes = {"aggregation": aggregation, "containment": "Unspecified"}
    if cardinality:
        type_attributes["multiplicity"] = str(cardinality)
    ET.SubElement(end, "type", type_attributes)
    ET.SubElement(end, "constraints")
    ET.SubElement(end, "modifiers", {"isOrdered": "false", "changeable": "none", "isNavigable": "false"})
    ET.SubElement(end, "style", {"value": "Union=0;Derived=0;AllowDuplicates=0;Owned=0;Navigable=Unspecified;"})
    ET.SubElement(end, "documentation")
    ET.SubElement(end, "xrefs")
    ET.SubElement(end, "tags")
    return data


def add_ea_connectors(extension: ET.Element, contenido: dict[str, Any]):
    connectors = ET.SubElement(extension, "connectors")
    nodes_by_id = {str(node.get("id")): node for node in contenido.get("nodes") or []}
    for index, edge in enumerate(contenido.get("edges") or [], start=1):
        source_id = str(edge.get("source"))
        target_id = str(edge.get("target"))
        if source_id not in nodes_by_id or target_id not in nodes_by_id:
            continue
        relation_id = exported_relation_id(edge)
        if not relation_id:
            continue
        relation_type = get_relation_type(edge)
        data = edge.get("data") or {}
        uses_multiplicity = relation_type in {"association", "associationClass", "composition", "aggregation"}
        source_aggregation = "composite" if relation_type == "composition" else "shared" if relation_type == "aggregation" else "none"
        connector = ET.SubElement(connectors, "connector", {xmi_attr("idref"): relation_id})
        add_ea_connector_end(
            connector,
            "source",
            nodes_by_id[source_id],
            data.get("sourceCardinality", "1") if uses_multiplicity else None,
            source_aggregation,
            data.get("sourceRole"),
        )
        add_ea_connector_end(
            connector,
            "target",
            nodes_by_id[target_id],
            data.get("targetCardinality", "0..*") if uses_multiplicity else None,
            "none",
            data.get("targetRole"),
        )
        ET.SubElement(connector, "model", {"ea_localid": str(2000 + index)})
        property_attributes = {
            "ea_type": relation_extension_name(edge),
            "direction": "Source -> Destination" if relation_type in {"generalization", "realization", "templateBinding"} else "Unspecified",
        }
        if relation_type == "associationClass":
            property_attributes["ea_type"] = "Association"
            property_attributes["subtype"] = "Class"
        ET.SubElement(connector, "properties", property_attributes)
        ET.SubElement(connector, "modifiers", {"isRoot": "false", "isLeaf": "false"})
        ET.SubElement(connector, "parameterSubstitutions")
        ET.SubElement(connector, "documentation")
        ET.SubElement(connector, "appearance", {"linemode": "3", "linecolor": "-1", "linewidth": "0", "seqno": "0", "headStyle": "0", "lineStyle": "0"})
        if uses_multiplicity:
            ET.SubElement(
                connector,
                "labels",
                {
                    "lb": str(data.get("sourceCardinality", "1")),
                    "rb": str(data.get("targetCardinality", "0..*")),
                },
            )
        else:
            ET.SubElement(connector, "labels")
        extended_attributes = {"virtualInheritance": "0"}
        if relation_type == "associationClass" and data.get("associationClassId"):
            extended_attributes["associationclass"] = safe_id(str(data["associationClassId"]))
        ET.SubElement(connector, "extendedProperties", extended_attributes)
        ET.SubElement(connector, "style")
        ET.SubElement(connector, "xrefs")
        tags = ET.SubElement(connector, "tags")
        if relation_type == "templateBinding":
            for name, value in (data.get("templateBindings") or {}).items():
                add_ea_tag(tags, f"templateBinding.{name}", value, relation_id)
    return connectors


def add_ea_primitive_types(extension: ET.Element, type_names: list[str]):
    primitive_types = ET.SubElement(extension, "primitivetypes")
    primitive_package = ET.SubElement(
        primitive_types,
        "packagedElement",
        {
            xmi_attr("type"): "uml:Package",
            xmi_attr("id"): "EAPrimitiveTypesPackage",
            "name": "EA_PrimitiveTypes_Package",
            "visibility": "public",
        },
    )
    language_package = ET.SubElement(
        primitive_package,
        "packagedElement",
        {
            xmi_attr("type"): "uml:Package",
            xmi_attr("id"): "EAJavaTypesPackage",
            "name": "EA_Java_Types_Package",
            "visibility": "public",
        },
    )
    for type_name in type_names:
        ET.SubElement(
            language_package,
            "packagedElement",
            {
                xmi_attr("type"): "uml:PrimitiveType",
                xmi_attr("id"): primitive_type_id(type_name),
                "name": type_name,
                "visibility": "public",
            },
        )


def add_enterprise_architect_diagram(
    extension: ET.Element,
    contenido: dict[str, Any],
    nombre: str,
    class_elements: dict[str, ET.Element],
    relation_ids: set[str],
    package_id: str,
):
    diagrams = ET.SubElement(extension, "diagrams")
    diagram_id = ea_guid("EAID", nombre or "DrawSchemaDiagram")
    diagram = ET.SubElement(
        diagrams,
        "diagram",
        {
            xmi_attr("id"): diagram_id,
        },
    )
    ET.SubElement(
        diagram,
        "model",
        {
            "package": package_id,
            "localID": "1",
            "owner": package_id,
        },
    )
    ET.SubElement(
        diagram,
        "properties",
        {
            "name": str(nombre or "DrawSchema Diagram"),
            "type": "Logical",
        },
    )
    ET.SubElement(
        diagram,
        "project",
        {
            "author": "DrawSchema",
            "version": "1.0",
        },
    )
    ET.SubElement(
        diagram,
        "style1",
        {
            "value": (
                "ShowPrivate=1;ShowProtected=1;ShowPublic=1;HideRelationships=0;"
                "Locked=0;Border=1;Zoom=100;HideAtts=0;HideOps=0;"
                "ConnectorNotation=UML 2.1;ShowNotes=0;"
            ),
        },
    )
    ET.SubElement(diagram, "style2", {"value": "ExcludeRTF=0;DocAll=0;HideQuals=0;"})
    ET.SubElement(diagram, "swimlanes", {"value": "locked=false;orientation=0;width=0;"})
    ET.SubElement(diagram, "matrixitems", {"value": "locked=false;matrixactive=false;"})
    ET.SubElement(diagram, "extendedProperties")
    diagram_elements = ET.SubElement(diagram, "elements")

    visible_nodes = [
        node
        for node in contenido.get("nodes", [])
        if str(node.get("id")) in class_elements
    ]
    normalized_positions, _ = normalized_diagram_positions(visible_nodes)

    for index, node in enumerate(visible_nodes, start=1):
        node_id = str(node.get("id"))
        x, y = normalized_positions[node_id]
        width, height = get_node_size(node)
        ET.SubElement(
            diagram_elements,
            "element",
            {
                "subject": safe_id(node_id),
                "geometry": geometry_value(x, y, width, height),
                "seqno": str(index),
                "style": f"DUID={diagram_object_id(node_id)};",
            },
        )

    for edge in contenido.get("edges", []):
        relation_id = exported_relation_id(edge)
        if relation_id is None or relation_id not in relation_ids:
            continue

        source = str(edge.get("source"))
        target = str(edge.get("target"))
        if source not in class_elements or target not in class_elements:
            continue

        ET.SubElement(
            diagram_elements,
            "element",
            {
                "subject": relation_id,
                "geometry": "SX=0;SY=0;EX=0;EY=0;EDGE=3;$LLB=;LLT=;LMT=;LMB=;LRT=;LRB=;IRHS=;ILHS=;Path=;",
                "style": (
                    f"Mode=3;SOID={diagram_object_id(source)};EOID={diagram_object_id(target)};"
                    "Color=-1;LWidth=0;Hidden=0;"
                ),
            },
        )


def diagram_content_to_xmi(
    contenido: dict[str, Any],
    nombre: str = "DrawSchemaModel",
    profile: str = STANDARD_PROFILE,
):
    if profile not in {STANDARD_PROFILE, ENTERPRISE_ARCHITECT_PROFILE}:
        raise ValueError(f"Perfil XMI no soportado: {profile}")

    root = ET.Element(
        f"{{{XMI_NS}}}XMI",
        {
            xmi_attr("version"): "2.1",
        },
    )

    if profile == ENTERPRISE_ARCHITECT_PROFILE:
        ET.SubElement(
            root,
            xmi_attr("Documentation"),
            {
                "exporter": "Enterprise Architect",
                "exporterVersion": "6.5",
            },
        )

    model = ET.SubElement(
        root,
        f"{{{UML_NS}}}Model",
        {
            xmi_attr("type"): "uml:Model",
            xmi_attr("id"): "DrawSchemaModel",
            "name": "EA_Model" if profile == ENTERPRISE_ARCHITECT_PROFILE else str(nombre),
            "visibility": "public",
        },
    )
    package_id = ea_guid("EAPK", nombre or "DrawSchemaPackage")
    package = ET.SubElement(
        model,
        "packagedElement",
        {
            xmi_attr("type"): "uml:Package",
            xmi_attr("id"): package_id,
            "name": str(nombre),
            "visibility": "public",
        },
    )

    class_elements: dict[str, ET.Element] = {}
    association_class_ids = {
        str((edge.get("data") or {}).get("associationClassId"))
        for edge in contenido.get("edges", [])
        if get_relation_type(edge) == "associationClass"
        and (edge.get("data") or {}).get("associationClassId")
    }
    type_names = collect_used_types(contenido)
    type_ids = (
        {type_name.casefold(): primitive_type_id(type_name) for type_name in type_names}
        if profile == ENTERPRISE_ARCHITECT_PROFILE
        else None
    )

    for node in contenido.get("nodes", []):
        node_id = str(node.get("id"))
        class_elements[node_id] = create_class_element(
            package,
            node,
            force_association_class=node_id in association_class_ids,
            type_ids=type_ids,
        )

    relation_ids: set[str] = set()
    for edge in contenido.get("edges", []):
        relation_type = get_relation_type(edge)

        if relation_type == "generalization":
            add_generalization(class_elements, edge)
        elif relation_type in {"association", "composition", "aggregation"}:
            add_association(package, edge)
        elif relation_type == "associationClass":
            add_association_class(class_elements, edge)
        elif relation_type in {"realization", "templateBinding"}:
            add_directed_relation(package, edge)

        relation_id = exported_relation_id(edge)
        if relation_id:
            relation_ids.add(relation_id)

    if profile == ENTERPRISE_ARCHITECT_PROFILE:
        extension = ET.SubElement(
            root,
            xmi_attr("Extension"),
            {
                "extender": "Enterprise Architect",
                "extenderID": "6.5",
            },
        )
        add_ea_elements(
            extension=extension,
            contenido=contenido,
            package_id=package_id,
            association_class_ids=association_class_ids,
        )
        add_ea_connectors(extension, contenido)
        add_ea_primitive_types(extension, type_names)
        add_enterprise_architect_diagram(
            extension=extension,
            contenido=contenido,
            nombre=nombre,
            class_elements=class_elements,
            relation_ids=relation_ids,
            package_id=package_id,
        )

    ET.indent(root, space="  ")
    output = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    if profile == ENTERPRISE_ARCHITECT_PROFILE:
        output = output.replace(XMI_NS.encode(), EA_XMI_NS.encode())
        output = output.replace(UML_NS.encode(), EA_UML_NS.encode())
    return output
