# Chat individual y grupal

Usa la misma base PostgreSQL de Neon y el esquema `diagramas`.
No se necesita otra base ni nuevas dependencias de ejecución.

## Activación

1. Comprueba que `DATABASE_URL` apunta a la rama Neon prevista, con la configuración SSL de su cadena de conexión.
2. Ejecuta `migrations/001_chat.sql` en el SQL Editor de esa rama (preferiblemente primero en una rama de desarrollo).
3. Reinicia el backend actualizado. Su `Base.metadata.create_all` existente también puede crear estas tablas si no existen; no duplica las ya creadas.
4. Abre `/docs`, autentícate y prueba los endpoints del grupo Chat.

El script solo añade tablas e índices. No ejecutarlo en una base diferente de la prevista.
`IF NOT EXISTS` permite reutilizarlo, pero no corrige una tabla previa con estructura incompatible.

## Contrato

- `POST /proyectos/{proyecto_id}/conversaciones`, cuerpo `{"tipo":"individual"}` o `{"tipo":"grupal"}`: obtiene o crea la conversación. Una individual por usuario/proyecto y una grupal por proyecto.
- `POST /conversaciones/{id}/mensajes`, cuerpo `{"texto":"Hola","diagrama_id":5}`: guarda un mensaje humano. El diagrama es opcional y debe pertenecer al proyecto.
- `GET /conversaciones/{id}/mensajes?limite=50`: últimos mensajes en orden cronológico.
- Para recuperar mensajes anteriores, utiliza `siguiente_antes_de` como `antes_de` en la siguiente petición. Prependa esa página al historial, no la reemplace.

Todos requieren JWT. El autor se obtiene del usuario autenticado. El cliente no puede enviar autor, rol ni resultado IA. Se comprueba la pertenencia vigente al proyecto en cada lectura/escritura, incluso para chats individuales.

`autor_nombre` conserva el nombre al escribir. Eliminar un proyecto elimina sus conversaciones; eliminar un usuario elimina su conversación privada y sus mensajes humanos, según las claves foráneas. Eliminar un diagrama conserva los mensajes y borra su referencia.

## Alcance

Incluye integración del frontend y respuestas IA de texto e imágenes. El backend solicita la respuesta al servicio configurado en AI_API_URL y la guarda con rol assistant; el cliente no puede elegir ese rol ni enviar una respuesta fabricada. No incluye WebSockets de chat ni almacenamiento del archivo de imagen original.

## Verificación

`venv\Scripts\python.exe -m unittest discover -s tests -v`

Las pruebas de chat comprueban permisos, validación, consultas, rollback y DDL PostgreSQL mediante dobles de sesión. No escriben en Neon ni reemplazan una prueba de integración real con dos usuarios y PostgreSQL.

## Integración IA

- Configurar AI_API_URL= https://iabackend-copia.onrender.com (desarrollo) en el backend.
- POST /conversaciones/{id}/mensajes/{mensaje_id}/respuesta-ia genera y guarda la respuesta de una consulta propia ya guardada.
- GET /conversaciones/{id}/contexto devuelve al servicio IA los últimos 20 mensajes autorizados, limitados por mensaje y con sus autores.
- POST /conversaciones/{id}/imagen recibe image y diagrama_id por multipart y guarda consulta/análisis. No almacena el archivo original.
- migrations/002_chat_ai_reply.sql crea el índice único para evitar respuestas duplicadas. El backend también crea este índice automáticamente al iniciar.
- Reiniciar ambos servicios. No se ejecutaron migraciones en Neon como parte de las pruebas.
- Si falla el modelo, el mensaje humano permanece guardado. El botón Obtener respuesta IA permite reintentar texto sin duplicar la consulta. Las respuestas previas a esta implementación que solo vivían en memoria no se recuperan retrospectivamente.
