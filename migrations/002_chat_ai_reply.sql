-- Evita respuestas duplicadas al reintentar una consulta.
CREATE UNIQUE INDEX IF NOT EXISTS uq_mensaje_respuesta_ia ON diagramas.mensajes (conversacion_id, (resultado_ia ->> 'reply_to')) WHERE rol = 'assistant' AND resultado_ia ? 'reply_to';
