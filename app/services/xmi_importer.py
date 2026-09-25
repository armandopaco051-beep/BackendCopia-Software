from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any


RELATION_TYPES = {
    "association": "association",
    "generalization": "generalization",
    "composition": "composition",
    "aggregation": "aggregation",
    "associationClass": "associationClass",
    "realization": "realization",
}

DEFINITION_TAGS = {"packagedElement", "ownedMember"}
CLASS_TYPES = {"Class", "Interface", "AssociationClass"}
GEOMETRY_PATTERN = re.compile(r"(Left|Top|Right|Bottom)=(-?\d+(?:\.\d+)?)")


def local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag.split(":")[-1]

        
def attr_by_suffix(element: ET.Element, suffix: str) -> str | None:
    for key, value in element.attrib.items():
        if key == suffix or key.endswith(f"}}{suffix}") or key.endswith(f":{suffix}"):
            return value
    return None


def xmi_id(element: ET.Element) -> str | None:
    return attr_by_suffix(element, "id")


def xmi_idref(element: ET.Element) -> str | None:
    return attr_by_suffix(element, "idref")


def xmi_type_name(element: ET.Element) -> str:
    value = attr_by_suffix(element, "type") or ""
    return value.split(":")[-1]


def is_packaged_definition(element: ET.Element) -> bool:
    return local_name(element.tag) in DEFINITION_TAGS


def href_fragment(value: str | None) -> str | None:
    if not value:
        return None
    return value.rsplit("#", 1)[-1]


def referenced_type_id(element: ET.Element) -> str | None:
    # Algunos XMI usan type="id" y Enterprise Architect usa <type xmi:idref="id"/>.
    direct_type = element.get("type")
    if direct_type and not direct_type.startswith("uml:"):
        return href_fragment(direct_type)

    for child in element:
        if local_name(child.tag) != "type":
            continue
        reference = xmi_idref(child) or child.get("idref") or child.get("href")
        if reference:
            return href_fragment(reference)

    return None


def get_type_name(type_id: str | None, primitive_types: dict[str, str]) -> str:
    if not type_id:
        return "String"
    if type_id in primitive_types:
        return primitive_types[type_id]
    if type_id.startswith("EAJava_"):
        return type_id.removeprefix("EAJava_")
    return type_id


def value_from_child(element: ET.Element, child_name: str) -> str | None:
    direct = element.get(child_name)
    if direct is not None:
        return direct

    for child in element:
        if local_name(child.tag) == f"{child_name}Value":
            return child.get("value")
    return None


def parse_lower_nullable(element: ET.Element) -> bool:
    return value_from_child(element, "lower") in {None, "0"}


def parse_cardinality(element: ET.Element) -> str:
    lower = value_from_child(element, "lower") or "1"
    upper = value_from_child(element, "upper") or "1"
    if upper in {"-1", "unlimited", "*"}:
        upper = "*"

    cardinality = lower if lower == upper else f"{lower}..{upper}"
    return cardinality if cardinality in {"1", "0..1", "0..*", "1..*"} else "1"


def parse_attributes(class_element: ET.Element, primitive_types: dict[str, str]) -> list[dict[str, Any]]:
    attributes: list[dict[str, Any]] = []
    for child in class_element:
        if local_name(child.tag) != "ownedAttribute" or child.get("association"):
            continue

        name = child.get("name") or "atributo"
        attributes.append(
            {
                "name": name,
                "type": get_type_name(referenced_type_id(child), primitive_types),
                "primaryKey": name.lower() in {"id", "codigo"},
                "nullable": parse_lower_nullable(child),
            }
        )
    return attributes


def parse_methods(class_element: ET.Element, primitive_types: dict[str, str]) -> list[dict[str, Any]]:
    methods: list[dict[str, Any]] = []
    for child in class_element:
        if local_name(child.tag) != "ownedOperation":
            continue

        parameters = []
        return_type = "void"
        for parameter in child:
            if local_name(parameter.tag) != "ownedParameter":
                continue

            parameter_type = get_type_name(referenced_type_id(parameter), primitive_types)
            if parameter.get("direction") == "return":
                return_type = parameter_type
            else:
                parameters.append(
                    {
                        "name": parameter.get("name") or "parametro",
                        "type": parameter_type,
                    }
                )

        methods.append(
            {
                "name": child.get("name") or "metodo",
                "returnType": return_type,
                "parameters": parameters,
            }
        )
    return methods


def collect_primitive_types(root: ET.Element) -> dict[str, str]:
    primitive_types: dict[str, str] = {}
    for element in root.iter():
        if xmi_type_name(element) != "PrimitiveType":
            continue
        element_id = xmi_id(element)
        name = element.get("name")
        if element_id and name:
            primitive_types[element_id] = name
    return primitive_types


def collect_class_definitions(root: ET.Element) -> dict[str, ET.Element]:
    definitions: dict[str, ET.Element] = {}
    for element in root.iter():
        if not is_packaged_definition(element) or xmi_type_name(element) not in CLASS_TYPES:
            continue

        element_id = xmi_id(element)
        name = element.get("name") or ""
        if not element_id or name.startswith("List of Elements in Package"):
            continue
        definitions.setdefault(element_id, element)
    return definitions


def parse_geometry(value: str | None) -> tuple[float, float] | None:
    if not value:
        return None
    values = {name: float(number) for name, number in GEOMETRY_PATTERN.findall(value)}
    if "Left" not in values or "Top" not in values:
        return None
    return values["Left"], values["Top"]


def collect_visible_layout(root: ET.Element, class_ids: set[str]) -> dict[str, tuple[float, float]]:
    candidates: list[dict[str, tuple[float, float]]] = []
    for diagram in root.iter():
        if local_name(diagram.tag) != "diagram":
            continue

        layout: dict[str, tuple[float, float]] = {}
        for element in diagram.iter():
            if local_name(element.tag) != "element":
                continue
            subject = element.get("subject")
            position = parse_geometry(element.get("geometry"))
            if subject in class_ids and position:
                layout[subject] = position
        if layout:
            candidates.append(layout)

    return max(candidates, key=len, default={})


def collect_classes(
    root: ET.Element,
    primitive_types: dict[str, str],
) -> tuple[list[dict[str, Any]], set[str], dict[str, ET.Element]]:
    definitions = collect_class_definitions(root)
    layout = collect_visible_layout(root, set(definitions))
    selected_ids = list(layout) if layout else list(definitions)

    if layout:
        min_x = min(position[0] for position in layout.values())
        min_y = min(position[1] for position in layout.values())

    nodes: list[dict[str, Any]] = []
    for index, class_id in enumerate(selected_ids):
        element = definitions[class_id]
        uml_type = xmi_type_name(element)
        if layout:
            raw_x, raw_y = layout[class_id]
            position = {"x": 100 + raw_x - min_x, "y": 100 + raw_y - min_y}
        else:
            position = {"x": 120 + (index % 4) * 280, "y": 100 + (index // 4) * 240}

        if uml_type == "Interface":
            kind = "interface"
        elif element.get("isAbstract", "false").lower() == "true":
            kind = "abstractClass"
        else:
            kind = "class"

        nodes.append(
            {
                "id": class_id,
                "type": "classNode",
                "position": position,
                "data": {
                    "name": element.get("name") or f"Clase{index + 1}",
                    "kind": kind,
                    "attributes": parse_attributes(element, primitive_types),
                    "methods": parse_methods(element, primitive_types),
                },
            }
        )

    return nodes, set(selected_ids), definitions


def collect_generalizations(
    definitions: dict[str, ET.Element], class_ids: set[str]
) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for child_id, class_element in definitions.items():
        if child_id not in class_ids:
            continue
        for relation in class_element:
            if local_name(relation.tag) != "generalization":
                continue
            parent_id = href_fragment(relation.get("general"))
            if parent_id not in class_ids:
                continue
            relation_id = xmi_id(relation) or f"rel-generalization-{child_id}-{parent_id}"
            edges.append(
                {
                    "id": relation_id,
                    "source": child_id,
                    "target": parent_id,
                    "type": "umlRelation",
                    "data": {
                        "relationType": "generalization",
                        "sourceClassId": child_id,
                        "targetClassId": parent_id,
                        "childClassId": child_id,
                        "parentClassId": parent_id,
                    },
                }
            )
    return edges


def resolve_association_ends(
    association: ET.Element,
    elements_by_id: dict[str, ET.Element],
) -> list[ET.Element]:
    ends = [child for child in association if local_name(child.tag) == "ownedEnd"]
    for child in association:
        if local_name(child.tag) != "memberEnd":
            continue
        reference = xmi_idref(child) or child.get("idref")
        referenced = elements_by_id.get(reference or "")
        if referenced is not None and referenced not in ends:
            ends.append(referenced)

    member_end_attr = (association.get("memberEnd") or "").split()
    for reference in member_end_attr:
        referenced = elements_by_id.get(reference)
        if referenced is not None and referenced not in ends:
            ends.append(referenced)
    return ends


def ordered_association_ends(ends: list[ET.Element]) -> tuple[ET.Element, ET.Element] | None:
    if len(ends) < 2:
        return None

    source = next((end for end in ends if "src" in (xmi_id(end) or "").lower()), None)
    target = next((end for end in ends if "dst" in (xmi_id(end) or "").lower()), None)
    if source is not None and target is not None and source is not target:
        return source, target
    return ends[0], ends[1]


def collect_associations(root: ET.Element, class_ids: set[str]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    elements_by_id = {element_id: element for element in root.iter() if (element_id := xmi_id(element))}

    for element in root.iter():
        uml_type = xmi_type_name(element)
        if not is_packaged_definition(element) or uml_type not in {"Association", "AssociationClass"}:
            continue

        ordered_ends = ordered_association_ends(resolve_association_ends(element, elements_by_id))
        if not ordered_ends:
            continue
        source_end, target_end = ordered_ends
        source_id = referenced_type_id(source_end)
        target_id = referenced_type_id(target_end)
        if source_id not in class_ids or target_id not in class_ids:
            continue

        source_aggregation = source_end.get("aggregation")
        target_aggregation = target_end.get("aggregation")
        relation_type = "associationClass" if uml_type == "AssociationClass" else "association"
        if "composite" in {source_aggregation, target_aggregation}:
            relation_type = "composition"
        elif "shared" in {source_aggregation, target_aggregation}:
            relation_type = "aggregation"

        # El modelo interno espera que source sea el Todo en composition/aggregation.
        if relation_type in {"composition", "aggregation"} and target_aggregation in {"composite", "shared"}:
            source_end, target_end = target_end, source_end
            source_id, target_id = target_id, source_id

        association_id = xmi_id(element) or f"association-{len(edges) + 1}"
        data: dict[str, Any] = {
            "relationType": relation_type,
            "sourceClassId": source_id,
            "targetClassId": target_id,
            "sourceCardinality": parse_cardinality(source_end),
            "targetCardinality": parse_cardinality(target_end),
        }
        if source_end.get("name"):
            data["sourceRole"] = source_end.get("name")
        if target_end.get("name"):
            data["targetRole"] = target_end.get("name")
        if relation_type in {"composition", "aggregation"}:
            data["wholeClassId"] = source_id
            data["partClassId"] = target_id
        if uml_type == "AssociationClass":
            data["associationClassId"] = association_id

        edges.append(
            {
                "id": f"rel-{association_id}" if uml_type == "AssociationClass" else association_id,
                "source": source_id,
                "target": target_id,
                "type": "umlRelation",
                "data": data,
            }
        )
    return edges


def parse_xmi_to_diagram_content(xmi_text: str) -> dict[str, list[dict[str, Any]]]:
    try:
        root = ET.fromstring(xmi_text)
    except ET.ParseError as exc:
        raise ValueError("El archivo XMI no tiene un XML valido") from exc

    primitive_types = collect_primitive_types(root)
    nodes, class_ids, definitions = collect_classes(root, primitive_types)
    edges = collect_generalizations(definitions, class_ids)
    edges.extend(collect_associations(root, class_ids))
    return {"nodes": nodes, "edges": edges}
