from copy import deepcopy
import unittest
from unittest.mock import MagicMock, patch

from app.services.relationship_keys import synchronize_relationship_keys, primary_keys
from app.services import diagrama
from app.models.diagrama import Diagrama
from app.schemas.diagrama import RelacionCreate, RelacionUpdate


def node(id, name, attributes=None):
    return {"id": id, "data": {"name": name, "attributes": attributes if attributes is not None else [{"name": "id", "type": "BIGINT", "primaryKey": True}]}}


def edge(source="c", target="v", kind="association", sc="1", tc="1..*", **extra):
    return {"id": "r", "source": source, "target": target, "data": {"relationType": kind, "sourceCardinality": sc, "targetCardinality": tc, **extra}}


def attributes(graph, id):
    return next(n["data"]["attributes"] for n in graph["nodes"] if n["id"] == id)


class RelationshipKeyTest(unittest.TestCase):
    def test_one_many_copies_key_as_foreign_only(self):
        graph = {"nodes": [node("c", "Cliente"), node("v", "Venta")], "edges": [edge()]}
        synchronize_relationship_keys(graph)
        sale = attributes(graph, "v")
        fk = next(a for a in sale if a.get("foreignKey"))
        self.assertFalse(fk["primaryKey"])
        self.assertEqual(fk["name"], "id_cliente")
        self.assertFalse(fk["nullable"])
        self.assertTrue(sale[0]["primaryKey"])
        self.assertEqual(len(attributes(graph, "c")), 1)

    def test_reverse_edge_and_optional_reference(self):
        graph = {"nodes": [node("c", "Cliente"), node("v", "Venta")], "edges": [edge("v", "c", sc="0..*", tc="0..1")]}
        synchronize_relationship_keys(graph)
        fk = next(a for a in attributes(graph, "v") if a.get("foreignKey"))
        self.assertTrue(fk["nullable"])
        self.assertEqual(fk["references"]["nodeId"], "c")

    def test_composite_keys_keep_types(self):
        graph = {"nodes": [node("c", "Cliente", [{"name": "pais", "type": "VARCHAR", "primaryKey": True}, {"name": "codigo", "type": "UUID", "primaryKey": True}]), node("v", "Venta")], "edges": [edge()]}
        synchronize_relationship_keys(graph)
        fks = [a for a in attributes(graph, "v") if a.get("foreignKey")]
        self.assertEqual({a["type"] for a in fks}, {"VARCHAR", "UUID"})
        self.assertFalse(any(a["primaryKey"] for a in fks))

    def test_association_class_has_composite_pk_fk_and_preserves_own_attributes(self):
        graph = {"nodes": [node("c", "Producto"), node("v", "Venta"), node("d", "DetalleVenta", [{"name": "cantidad", "type": "INTEGER"}])], "edges": [edge(kind="associationClass", sc="0..*", tc="1..*", associationClassId="d")]}
        synchronize_relationship_keys(graph)
        attrs = attributes(graph, "d")
        self.assertEqual(len([a for a in attrs if a.get("primaryKey") and a.get("foreignKey")]), 2)
        self.assertIn("cantidad", [a["name"] for a in attrs])
        previous = deepcopy(graph)
        synchronize_relationship_keys(graph)
        self.assertEqual(graph, previous)

    def test_reassign_and_delete_remove_only_generated_keys(self):
        graph = {"nodes": [node("c", "Cliente"), node("v", "Venta"), node("p", "Producto"), node("d", "DetalleVenta", [{"name": "cantidad"}])], "edges": [edge("c", "p", kind="associationClass", associationClassId="d")]}
        synchronize_relationship_keys(graph)
        graph["edges"][0]["source"] = "v"
        synchronize_relationship_keys(graph)
        names = [a["name"] for a in attributes(graph, "d")]
        self.assertNotIn("id_cliente", names)
        self.assertIn("id_venta", names)
        graph["edges"] = []
        synchronize_relationship_keys(graph)
        self.assertEqual(attributes(graph, "d"), [{"name": "cantidad"}])

    def test_composition_and_aggregation_do_not_promote_fk_to_pk(self):
        for kind in ("composition", "aggregation"):
            graph = {"nodes": [node("c", "Todo"), node("v", "Parte")], "edges": [edge(kind=kind)]}
            synchronize_relationship_keys(graph)
            fk = next(a for a in attributes(graph, "v") if a.get("foreignKey"))
            self.assertFalse(fk["primaryKey"])

    def test_joined_child_key_is_primary_and_foreign(self):
        graph = {"nodes": [node("c", "Persona"), node("v", "Empleado")], "edges": [edge("v", "c", kind="generalization")]}
        synchronize_relationship_keys(graph)
        pk = primary_keys(graph["nodes"][1])[0]
        self.assertTrue(pk["foreignKey"])
        self.assertEqual(pk["references"]["nodeId"], "c")
        graph["edges"] = []
        synchronize_relationship_keys(graph)
        self.assertNotIn("foreignKey", attributes(graph, "v")[0])

    def test_single_table_and_realization_do_not_copy_keys(self):
        for relation in (edge("v", "c", kind="generalization", inheritanceStrategy="SINGLE_TABLE"), edge("v", "c", kind="realization")):
            graph = {"nodes": [node("c", "Persona"), node("v", "Empleado")], "edges": [relation]}
            synchronize_relationship_keys(graph)
            self.assertFalse(any(a.get("foreignKey") for a in attributes(graph, "v")))

    def test_no_invented_pk_and_no_arbitrary_one_one_or_many_many_fk(self):
        for relation in (edge(), edge(sc="1", tc="1"), edge(sc="0..*", tc="1..*")):
            graph = {"nodes": [node("c", "Cliente", []), node("v", "Venta")], "edges": [relation]}
            synchronize_relationship_keys(graph)
            self.assertEqual(len(attributes(graph, "v")), 1)


class SaveRelationshipKeysTest(unittest.TestCase):
    @patch.object(diagrama, "guardar_version_automatica")
    @patch.object(diagrama, "obtener_diagrama")
    def test_relation_save_returns_generated_fk_immediately(self, load, checkpoint):
        graph = {"nodes": [node("c", "Cliente"), node("v", "Venta")], "edges": []}
        current = Diagrama(id=1, nombre="Prueba", id_proyecto=1, version=1, contenido=graph)
        load.return_value = current
        relation = edge()
        result, error = diagrama.agregar_relacion(MagicMock(), 1, RelacionCreate(source="c", target="v", data=relation["data"]))
        self.assertIsNone(error)
        self.assertTrue(any(a.get("foreignKey") for a in attributes(result.contenido, "v")))
