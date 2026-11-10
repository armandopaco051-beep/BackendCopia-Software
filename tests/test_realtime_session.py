import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import WebSocketDisconnect
from app.routers import realtime


class RealtimeSessionTest(unittest.IsolatedAsyncioTestCase):
    @patch.object(realtime, "usuario_tiene_permiso", return_value=True)
    @patch.object(realtime, "obtener_diagrama", return_value=SimpleNamespace(id_proyecto=2))
    @patch.object(realtime, "get_user_from_token")
    @patch.object(realtime, "SessionLocal")
    async def test_database_session_closed_before_websocket_connect(self, sessions, user, diagram, permission):
        user.return_value = SimpleNamespace(codigo="u1", nombres="Ana", apellidos="Perez", email="ana@test.local")
        socket = MagicMock()
        socket.send_json = AsyncMock()
        socket.receive_json = AsyncMock(side_effect=WebSocketDisconnect())

        async def connected(*args):
            sessions.return_value.__exit__.assert_called_once()

        with patch.object(realtime.realtime_manager, "connect", new_callable=AsyncMock, side_effect=connected), \
             patch.object(realtime.realtime_manager, "broadcast", new_callable=AsyncMock), \
             patch.object(realtime.realtime_manager, "get_users", new_callable=AsyncMock, return_value=[]), \
             patch.object(realtime.realtime_manager, "disconnect", new_callable=AsyncMock, return_value=None):
            await realtime.diagram_realtime_socket(socket, 34, "token")
        self.assertEqual(permission.call_count, 2)

    @patch.object(realtime, "get_user_from_token", return_value=None)
    @patch.object(realtime, "SessionLocal")
    async def test_invalid_user_closes_session_and_rejects_socket(self, sessions, user):
        socket = MagicMock()
        socket.close = AsyncMock()
        await realtime.diagram_realtime_socket(socket, 34, "bad-token")
        sessions.return_value.__exit__.assert_called_once()
        socket.close.assert_awaited_once_with(code=1008)
