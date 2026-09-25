import unittest
import xml.etree.ElementTree as ET

from app.services.xmi_exporter import (
    ENTERPRISE_ARCHITECT_PROFILE,
    XMI_NS,
    diagram_content_to_xmi,
)
from app.services.xmi_importer import parse_xmi_to_diagram_content


def xmi_type(element: ET.Element):
    for key, value in element.attrib.items():
        if key == "type" or key.endswith("}type"):
            return value
    return None


def local_name(tag: str):
    return tag.rsplit("}", 1)[-1]


class XmiExporterTest(unittest.TestCase):
    def test_standard_profile_does_not_include_enterprise_architect_diagram(self):
        root = ET.fromstring(
            diagram_content_to_xmi(
                {"nodes": [{"id": "cliente", "data": {"name": "Cliente"}}], "edges": []},
                "Ventas",
            )
        )

        self.assertFalse(any(local_name(item.tag) == "diagram" for item in root.iter()))

    def test_enterprise_architect_profile_exports_layout_and_links(self):
        content = {
            "nodes": [
                {
                    "id": "cliente",
                    "position": {"x": 100, "y": 200},
                    "style": {"width": 300, "height": 220},
                    "data": {"name": "Cliente", "attributes": [], "methods": []},
                },
                {
                    "id": "pedido",
                    "position": {"x": 500, "y": 250},
                    "data": {"name": "Pedido", "attributes": [], "methods": []},
                },
            ],
            "edges": [
                {
                    "id": "rel-cliente-pedido",
                    "source": "cliente",
                    "target": "pedido",
                    "data": {
                        "relationType": "association",
                        "sourceCardinality": "1",
                        "targetCardinality": "0..*",
                    },
                }
            ],
        }

        root = ET.fromstring(
            diagram_content_to_xmi(content, "Ventas", ENTERPRISE_ARCHITECT_PROFILE)
        )
        self.assertEqual(root.tag, "{http://schema.omg.org/spec/XMI/2.1}XMI")
        diagrams = [item for item in root.iter() if local_name(item.tag) == "diagram"]
        self.assertEqual(len(diagrams), 1)

        visual_elements = [
            item
            for item in diagrams[0].iter()
            if local_name(item.tag) == "element" and item.get("subject")
            and "Left=" in (item.get("geometry") or "")
        ]
        visual_links = [
            item
            for item in diagrams[0].iter()
            if local_name(item.tag) == "element" and "EDGE=" in (item.get("geometry") or "")
        ]
        diagram_model = next(item for item in diagrams[0] if local_name(item.tag) == "model")

        self.assertEqual([item.get("subject") for item in visual_elements], ["cliente", "pedido"])
        self.assertEqual(
            visual_elements[0].get("geometry"),
            "Left=40;Top=40;Right=140;Bottom=92;",
        )
        self.assertEqual(
            visual_elements[1].get("geometry"),
            "Left=440;Top=90;Right=540;Bottom=142;",
        )
        self.assertEqual(len(visual_links), 1)
        self.assertEqual(visual_links[0].get("subject"), "rel_cliente_pedido")
        self.assertTrue(diagram_model.get("package", "").startswith("EAPK_"))
        self.assertEqual(diagram_model.get("owner"), diagram_model.get("package"))

    def test_enterprise_architect_export_can_be_imported_without_duplicates(self):
        content = {
            "nodes": [
                {
                    "id": "class-a",
                    "position": {"x": 20, "y": 30},
                    "data": {"name": "Cliente", "attributes": [], "methods": []},
                },
                {
                    "id": "class-b",
                    "position": {"x": 360, "y": 30},
                    "data": {"name": "Pedido", "attributes": [], "methods": []},
                },
            ],
            "edges": [
                {
                    "id": "rel-1",
                    "source": "class-a",
                    "target": "class-b",
                    "data": {
                        "relationType": "association",
                        "sourceCardinality": "1",
                        "targetCardinality": "0..*",
                    },
                }
            ],
        }

        exported = diagram_content_to_xmi(
            content,
            "Ventas",
            ENTERPRISE_ARCHITECT_PROFILE,
        ).decode("utf-8")
        imported = parse_xmi_to_diagram_content(exported)

        self.assertEqual(len(imported["nodes"]), 2)
        self.assertEqual({node["data"]["name"] for node in imported["nodes"]}, {"Cliente", "Pedido"})
        self.assertEqual(len(imported["edges"]), 1)
        self.assertEqual(imported["edges"][0]["data"]["relationType"], "association")
        self.assertEqual(imported["edges"][0]["data"]["sourceCardinality"], "1")
        self.assertEqual(imported["edges"][0]["data"]["targetCardinality"], "0..*")

    def test_exports_binary_association_with_multiplicities(self):
        content = {
            "nodes": [
                {"id": "class-a", "data": {"name": "Cliente"}},
                {"id": "class-b", "data": {"name": "Pedido"}},
            ],
            "edges": [
                {
                    "id": "rel-1",
                    "source": "class-a",
                    "target": "class-b",
                    "data": {
                        "relationType": "association",
                        "sourceCardinality": "1",
                        "targetCardinality": "0..*",
                    },
                }
            ],
        }

        root = ET.fromstring(diagram_content_to_xmi(content, "Ventas"))
        association = next(
            item for item in root.iter() if xmi_type(item) == "uml:Association"
        )
        ends = [item for item in association if item.tag == "ownedEnd"]

        self.assertEqual(association.get("memberEnd"), "rel_1_source rel_1_target")
        self.assertNotIn("name", association.attrib)
        self.assertEqual(len(ends), 2)
        self.assertTrue(all(xmi_type(item) == "uml:Property" for item in ends))
        self.assertEqual(ends[0].find("lowerValue").get("value"), "1")
        self.assertEqual(ends[0].find("upperValue").get("value"), "1")
        self.assertEqual(ends[1].find("lowerValue").get("value"), "0")
        self.assertEqual(ends[1].find("upperValue").get("value"), "*")

    def test_exports_composition_diamond_on_whole_end(self):
        content = {
            "nodes": [
                {"id": "order", "data": {"name": "Pedido"}},
                {"id": "item", "data": {"name": "DetallePedido"}},
            ],
            "edges": [
                {
                    "id": "composition-1",
                    "source": "order",
                    "target": "item",
                    "data": {
                        "relationType": "composition",
                        "sourceCardinality": "1",
                        "targetCardinality": "1..*",
                    },
                }
            ],
        }

        root = ET.fromstring(diagram_content_to_xmi(content, "Pedidos"))
        association = next(
            item for item in root.iter() if xmi_type(item) == "uml:Association"
        )
        ends = [item for item in association if item.tag == "ownedEnd"]

        source_type = next(item for item in ends[0] if local_name(item.tag) == "type")
        self.assertEqual(
            next(value for key, value in source_type.attrib.items() if key.endswith("}idref")),
            "order",
        )
        self.assertEqual(ends[0].get("aggregation"), "composite")
        self.assertEqual(ends[1].get("aggregation"), "none")
        self.assertEqual(ends[0].find("lowerValue").get("value"), "1")
        self.assertEqual(ends[1].find("lowerValue").get("value"), "1")
        self.assertEqual(ends[1].find("upperValue").get("value"), "*")

    def test_exports_association_class_as_uml_association_class(self):
        content = {
            "nodes": [
                {"id": "student", "data": {"name": "Estudiante"}},
                {"id": "subject", "data": {"name": "Materia"}},
                {
                    "id": "enrollment",
                    "data": {
                        "name": "Inscripcion",
                        "attributes": [{"name": "fecha", "type": "DATE"}],
                    },
                },
            ],
            "edges": [
                {
                    "id": "association-class-1",
                    "source": "student",
                    "target": "subject",
                    "data": {
                        "relationType": "associationClass",
                        "associationClassId": "enrollment",
                        "sourceCardinality": "0..*",
                        "targetCardinality": "0..*",
                    },
                }
            ],
        }

        root = ET.fromstring(diagram_content_to_xmi(content, "Academico"))
        association_class = next(
            item for item in root.iter() if xmi_type(item) == "uml:AssociationClass"
        )
        association_elements = [
            item for item in root.iter() if xmi_type(item) == "uml:Association"
        ]

        self.assertEqual(association_class.get("name"), "Inscripcion")
        self.assertEqual(
            association_class.get("memberEnd"),
            "association_class_1_source association_class_1_target",
        )
        self.assertEqual(len(association_elements), 0)
        self.assertEqual(
            [item.get("association") for item in association_class.findall("ownedEnd")],
            ["enrollment", "enrollment"],
        )

    def test_exports_realization_and_template_binding(self):
        content = {
            "nodes": [
                {"id": "service", "data": {"name": "Servicio"}},
                {"id": "contract", "data": {"name": "Contrato", "kind": "interface"}},
                {"id": "repository", "data": {"name": "Repositorio<T>"}},
            ],
            "edges": [
                {
                    "id": "realization-1",
                    "source": "service",
                    "target": "contract",
                    "data": {"relationType": "realization"},
                },
                {
                    "id": "binding-1",
                    "source": "service",
                    "target": "repository",
                    "data": {
                        "relationType": "templateBinding",
                        "templateBindings": {"T": "Servicio"},
                    },
                },
            ],
        }

        root = ET.fromstring(
            diagram_content_to_xmi(content, "Servicios", ENTERPRISE_ARCHITECT_PROFILE)
        )
        realization = next(item for item in root.iter() if xmi_type(item) == "uml:Realization")
        dependency = next(item for item in root.iter() if xmi_type(item) == "uml:Dependency")
        diagram = next(item for item in root.iter() if local_name(item.tag) == "diagram")
        link_subjects = {
            item.get("subject")
            for item in diagram.iter()
            if local_name(item.tag) == "element" and "EDGE=" in (item.get("geometry") or "")
        }

        self.assertEqual((realization.get("client"), realization.get("supplier")), ("service", "contract"))
        self.assertEqual((dependency.get("client"), dependency.get("supplier")), ("service", "repository"))
        self.assertEqual(dependency.get("name"), "templateBinding")
        self.assertEqual(link_subjects, {"realization_1", "binding_1"})

    def test_enterprise_architect_exports_types_features_and_connectors(self):
        content = {
            "nodes": [
                {
                    "id": "customer",
                    "data": {
                        "name": "Cliente",
                        "attributes": [
                            {
                                "name": "id",
                                "type": "BIGINT",
                                "primaryKey": True,
                                "nullable": False,
                            },
                            {
                                "name": "email",
                                "type": "VARCHAR(150)",
                                "unique": True,
                                "nullable": False,
                            },
                        ],
                        "methods": [
                            {
                                "name": "buscar",
                                "returnType": "Cliente",
                                "parameters": [{"name": "codigo", "type": "BIGINT"}],
                            }
                        ],
                    },
                },
                {"id": "order", "data": {"name": "Pedido"}},
            ],
            "edges": [
                {
                    "id": "customer-orders",
                    "source": "customer",
                    "target": "order",
                    "data": {
                        "relationType": "association",
                        "sourceCardinality": "1",
                        "targetCardinality": "0..*",
                    },
                }
            ],
        }

        root = ET.fromstring(
            diagram_content_to_xmi(content, "Ventas", ENTERPRISE_ARCHITECT_PROFILE)
        )
        primitive_names = {
            item.get("name")
            for item in root.iter()
            if xmi_type(item) == "uml:PrimitiveType"
        }
        extension_attributes = [
            item for item in root.iter() if local_name(item.tag) == "attribute"
        ]
        connectors = [item for item in root.iter() if local_name(item.tag) == "connector"]
        operations = [item for item in root.iter() if local_name(item.tag) == "operation"]

        self.assertEqual(primitive_names, {"BIGINT", "VARCHAR(150)", "Cliente"})
        self.assertEqual(
            [next(child for child in item if local_name(child.tag) == "properties").get("type") for item in extension_attributes],
            ["BIGINT", "VARCHAR(150)"],
        )
        self.assertTrue(
            all(
                next(
                    value
                    for key, value in item.attrib.items()
                    if key == "idref" or key.endswith("}idref")
                ).startswith("EAID_")
                for item in extension_attributes
            )
        )
        self.assertEqual(len(operations), 1)
        self.assertEqual(len(connectors), 1)
        source = next(item for item in connectors[0] if local_name(item.tag) == "source")
        target = next(item for item in connectors[0] if local_name(item.tag) == "target")
        source_type = next(item for item in source if local_name(item.tag) == "type")
        target_type = next(item for item in target if local_name(item.tag) == "type")
        self.assertEqual(source_type.get("multiplicity"), "1")
        self.assertEqual(target_type.get("multiplicity"), "0..*")


if __name__ == "__main__":
    unittest.main()
