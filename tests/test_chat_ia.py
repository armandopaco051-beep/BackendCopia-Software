import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.services import chat_ia


class ChatAiTest(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.user = SimpleNamespace(codigo="u1", nombres="Ana", apellidos="Pérez")
        self.conversation = SimpleNamespace(id=10, proyecto_id=2)
        self.query = SimpleNamespace(id=3, diagrama_id=None, texto="Explica el modelo")
        self.plan = {"intent": "explain_diagram", "summary": "Es una biblioteca.",
                     "actions": [], "questions": [], "can_execute": False}

    @patch.object(chat_ia, "obtener_conversacion_autorizada")
    @patch.object(chat_ia, "solicitar_ia")
    def test_retry_from_different_active_diagram_is_rejected(self, request, access):
        access.return_value = self.conversation
        self.query.diagrama_id = 5
        self.db.query.return_value.filter.return_value.first.return_value = self.query
        with self.assertRaises(HTTPException) as caught:
            chat_ia.generar_respuesta(self.db, 10, 3, self.user, "token", expected_diagrama_id=9)
        self.assertEqual(caught.exception.status_code, 409)
        request.assert_not_called()

    @patch.object(chat_ia, "obtener_conversacion_autorizada")
    @patch.object(chat_ia, "solicitar_ia")
    def test_answer_is_saved_with_trusted_role_and_query_reference(self, request, access):
        access.return_value = self.conversation
        self.db.query.return_value.filter.return_value.first.side_effect = [self.query, None]
        request.return_value = self.plan
        result = chat_ia.generar_respuesta(self.db, 10, 3, self.user, "test-token")
        self.assertEqual(result.rol, "assistant")
        self.assertIsNone(result.autor_codigo)
        self.assertEqual(result.texto, "Es una biblioteca.")
        self.assertEqual(result.resultado_ia["reply_to"], "3")
        self.assertEqual(result.resultado_ia["destinatario_codigo"], "u1")
        self.assertEqual(result.resultado_ia["destinatario_nombre"], "Ana Pérez")
        self.assertEqual(result.conversacion_id, 10)
        self.db.commit.assert_called_once()
        self.assertEqual(access.call_count, 2)
        payload = json.loads(request.call_args.args[1])
        self.assertEqual(payload["conversacion_id"], 10)
        self.assertEqual(payload["mensaje_id"], 3)
        self.assertEqual(payload["text_provider"], "gemini")
        self.assertEqual(result.resultado_ia["provider"], "gemini")

    @patch.object(chat_ia, "obtener_conversacion_autorizada")
    @patch.object(chat_ia, "solicitar_ia")
    def test_local_selection_is_forwarded_and_saved(self, request, access):
        access.return_value = self.conversation
        self.db.query.return_value.filter.return_value.first.side_effect = [self.query, None]
        request.return_value = {**self.plan, "provider": "local", "model": "openai/qwen2.5-coder:1.5b"}
        result = chat_ia.generar_respuesta(self.db, 10, 3, self.user, "token", text_provider="local")
        self.assertEqual(json.loads(request.call_args.args[1])["text_provider"], "local")
        self.assertEqual(result.resultado_ia["provider"], "local")

    @patch.object(chat_ia, "obtener_conversacion_autorizada")
    @patch.object(chat_ia, "solicitar_ia")
    def test_retry_reuses_saved_answer(self, request, access):
        access.return_value = self.conversation
        answer = SimpleNamespace(id=4)
        self.db.query.return_value.filter.return_value.first.side_effect = [self.query, answer]
        self.assertIs(chat_ia.generar_respuesta(self.db, 10, 3, self.user, "token"), answer)
        request.assert_not_called()
        self.db.add.assert_not_called()

    @patch.object(chat_ia, "obtener_conversacion_autorizada")
    @patch.object(chat_ia, "solicitar_ia")
    def test_cannot_answer_someone_elses_private_or_missing_query(self, request, access):
        access.return_value = self.conversation
        self.db.query.return_value.filter.return_value.first.return_value = None
        with self.assertRaises(HTTPException) as caught:
            chat_ia.generar_respuesta(self.db, 10, 3, self.user, "token")
        self.assertEqual(caught.exception.status_code, 404)
        request.assert_not_called()

    @patch.object(chat_ia, "obtener_conversacion_autorizada")
    @patch.object(chat_ia, "solicitar_ia")
    def test_invalid_provider_response_is_not_saved(self, request, access):
        access.return_value = self.conversation
        self.db.query.return_value.filter.return_value.first.side_effect = [self.query, None]
        request.return_value = {"summary": "incomplete"}
        with self.assertRaises(HTTPException) as caught:
            chat_ia.generar_respuesta(self.db, 10, 3, self.user, "token")
        self.assertEqual(caught.exception.status_code, 502)
        self.db.add.assert_not_called()

    @patch.object(chat_ia, "urlopen", side_effect=TimeoutError())
    def test_timeout_has_clear_retry_message(self, _request):
        with self.assertRaises(HTTPException) as caught:
            chat_ia.solicitar_ia("/ai/planner", b"{}", "token")
        self.assertEqual(caught.exception.status_code, 504)

    def test_known_local_error_explains_failure_without_raw_traceback(self):
        from io import BytesIO
        from urllib.error import HTTPError
        error = HTTPError("http://ai/ai/planner", 502, "Bad Gateway", {}, BytesIO(json.dumps({
            "detail": {"code": "LOCAL_OUTPUT_TRUNCATED", "message": "El modelo local agotó el límite de respuesta."},
        }).encode()))
        with patch.object(chat_ia, "urlopen", side_effect=error), self.assertRaises(HTTPException) as caught:
            chat_ia.solicitar_ia("/ai/planner", b"{}", "token")
        self.assertIn("agotó el límite", caught.exception.detail)

    def test_unknown_service_error_does_not_expose_details(self):
        from io import BytesIO
        from urllib.error import HTTPError
        error = HTTPError("http://ai/ai/planner", 500, "Error", {}, BytesIO(b'{"detail":"private traceback"}'))
        with patch.object(chat_ia, "urlopen", side_effect=error), self.assertRaises(HTTPException) as caught:
            chat_ia.solicitar_ia("/ai/planner", b"{}", "token")
        self.assertNotIn("private traceback", caught.exception.detail)
