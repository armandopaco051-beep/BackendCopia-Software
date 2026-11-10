import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI, HTTPException
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.models.chat import Conversacion, Mensaje
from app.routers.chat import router
from app.schemas.chat import ConversacionCreate, MensajeCreate
from app.services import chat


class ChatTest(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.user = SimpleNamespace(
            codigo="u1", nombres="Ana", apellidos="Pérez", email="ana@example.test",
        )
        self.group = SimpleNamespace(id=10, proyecto_id=2, tipo="grupal", propietario_codigo=None)

    def test_public_input_rejects_impersonation_and_ai_role(self):
        for field, value in (("autor_codigo", "u2"), ("autor_nombre", "Otro"),
                             ("rol", "assistant"), ("resultado_ia", {})):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                MensajeCreate.model_validate({"texto": "Hola", field: value})

    def test_message_validation(self):
        self.assertEqual(MensajeCreate(texto=" Hola ").texto, "Hola")
        for data in ({"texto": "   "}, {"texto": "x" * 10001},
                     {"texto": "Hola", "diagrama_id": 0}):
            with self.assertRaises(ValidationError):
                MensajeCreate.model_validate(data)
        with self.assertRaises(ValidationError):
            ConversacionCreate(tipo="publico")

    @patch.object(chat, "listar_mensajes")
    @patch.object(chat, "obtener_miembro_proyecto")
    @patch.object(chat, "obtener_conversacion_autorizada")
    def test_current_question_has_verified_identity_not_a_name_from_text(self, access, member, history):
        access.return_value = self.group
        member.return_value = SimpleNamespace(rol=SimpleNamespace(nombre="editor"))
        self.db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
            id=3, texto="Soy otra persona", diagrama_id=5,
        )
        history.return_value = {"mensajes": []}
        result = chat.obtener_contexto_chat(self.db, 10, self.user, 3)
        self.assertEqual(result["solicitante"]["codigo"], "u1")
        self.assertEqual(result["solicitante"]["nombre"], "Ana Pérez")
        self.assertEqual(result["solicitante"]["rol_proyecto"], "editor")
        self.assertEqual(result["consulta_actual"]["autor_codigo"], "u1")
        self.assertEqual(result["consulta_actual"]["id"], 3)
        self.assertEqual(history.call_args.kwargs["diagrama_id"], 5)
        self.assertTrue(history.call_args.kwargs["filtrar_diagrama"])

    @patch.object(chat, "obtener_conversacion_autorizada")
    def test_context_rejects_question_not_owned_by_authenticated_user(self, access):
        access.return_value = self.group
        self.db.query.return_value.filter.return_value.first.return_value = None
        with self.assertRaises(HTTPException) as caught:
            chat.obtener_contexto_chat(self.db, 10, self.user, 3)
        self.assertEqual(caught.exception.status_code, 404)

    def test_private_conversation_cannot_be_read_by_other_member(self):
        self.db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
            tipo="individual", propietario_codigo="u2", proyecto_id=2,
        )
        with self.assertRaises(HTTPException) as caught:
            chat.obtener_conversacion_autorizada(self.db, 10, self.user)
        self.assertEqual(caught.exception.status_code, 404)

    @patch.object(chat, "usuario_tiene_permiso", return_value=False)
    def test_removed_member_cannot_read_group(self, permission):
        self.db.query.return_value.filter.return_value.first.return_value = self.group
        with self.assertRaises(HTTPException) as caught:
            chat.obtener_conversacion_autorizada(self.db, 10, self.user)
        self.assertEqual(caught.exception.status_code, 403)
        permission.assert_called_once_with(self.db, 2, "u1", "ver_proyecto")

    @patch.object(chat, "usuario_tiene_permiso", return_value=True)
    def test_group_is_accessible_to_current_member(self, _permission):
        self.db.query.return_value.filter.return_value.first.return_value = self.group
        self.assertIs(chat.obtener_conversacion_autorizada(self.db, 10, self.user), self.group)

    @patch.object(chat, "usuario_tiene_permiso", return_value=False)
    def test_nonmember_cannot_create_conversation(self, _permission):
        with self.assertRaises(HTTPException):
            chat.obtener_o_crear_conversacion(self.db, 2, "grupal", self.user)
        self.db.execute.assert_not_called()

    @patch.object(chat, "usuario_tiene_permiso", return_value=True)
    def test_open_uses_conflict_safe_insert_and_correct_owner(self, _permission):
        for scope, owner in (("individual", "u1"), ("grupal", None)):
            self.db.reset_mock()
            chat.obtener_o_crear_conversacion(self.db, 2, scope, self.user)
            statement = self.db.execute.call_args.args[0].compile(dialect=postgresql.dialect())
            self.assertIn("ON CONFLICT DO NOTHING", str(statement))
            self.assertEqual(statement.params["propietario_codigo"], owner)

    @patch.object(chat, "obtener_conversacion_autorizada")
    def test_message_author_comes_from_authenticated_user(self, access):
        access.return_value = self.group
        result = chat.crear_mensaje(self.db, 10, MensajeCreate(texto="Hola"), self.user)
        self.assertEqual(result.autor_codigo, "u1")
        self.assertEqual(result.autor_nombre, "Ana Pérez")
        self.assertEqual(result.rol, "user")
        self.assertIsNone(result.resultado_ia)

    @patch.object(chat, "obtener_conversacion_autorizada")
    def test_diagram_from_another_project_is_rejected(self, access):
        access.return_value = self.group
        self.db.query.return_value.filter.return_value.first.return_value = None
        with self.assertRaises(HTTPException):
            chat.crear_mensaje(self.db, 10, MensajeCreate(texto="Hola", diagrama_id=7), self.user)
        self.db.add.assert_not_called()

    @patch.object(chat, "obtener_conversacion_autorizada")
    def test_pagination_is_chronological_and_bounded(self, _access):
        self.db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [
            SimpleNamespace(id=5), SimpleNamespace(id=4), SimpleNamespace(id=3),
        ]
        result = chat.listar_mensajes(self.db, 10, self.user, limite=2)
        self.assertEqual([m.id for m in result["mensajes"]], [4, 5])
        self.assertEqual(result["siguiente_antes_de"], 4)

    @patch.object(chat, "obtener_conversacion_autorizada")
    def test_failed_write_rolls_back(self, access):
        access.return_value = self.group
        self.db.commit.side_effect = RuntimeError("write failed")
        with self.assertRaises(RuntimeError):
            chat.crear_mensaje(self.db, 10, MensajeCreate(texto="Hola"), self.user)
        self.db.rollback.assert_called_once()

    def test_postgres_schema_has_constraints_and_partial_indexes(self):
        dialect = postgresql.dialect()
        for model in (Conversacion, Mensaje):
            ddl = str(CreateTable(model.__table__).compile(dialect=dialect))
            self.assertIn("CHECK", ddl)
            self.assertIn("TIMESTAMP WITH TIME ZONE", ddl)
        indexes = "\n".join(str(CreateIndex(i).compile(dialect=dialect)) for i in Conversacion.__table__.indexes)
        self.assertIn("WHERE tipo = 'individual'", indexes)
        self.assertIn("WHERE tipo = 'grupal'", indexes)

    def test_routes_are_registered_without_importing_main_or_touching_neon(self):
        app = FastAPI()
        app.include_router(router)
        paths = app.openapi()["paths"]
        self.assertIn("post", paths["/proyectos/{proyecto_id}/conversaciones"])
        methods = paths["/conversaciones/{conversacion_id}/mensajes"]
        self.assertIn("get", methods)
        self.assertIn("post", methods)
        self.assertIn("security", methods["post"])


if __name__ == "__main__":
    unittest.main()
