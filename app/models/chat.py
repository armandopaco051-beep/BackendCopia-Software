from sqlalchemy import (
    BigInteger, CheckConstraint, Column, DateTime, ForeignKey,
    Identity, Index, Integer, String, Text, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB

from app.database import Base


class Conversacion(Base):
    __tablename__ = "conversaciones"
    __table_args__ = (
        CheckConstraint(
            "(tipo = 'individual' AND propietario_codigo IS NOT NULL) OR "
            "(tipo = 'grupal' AND propietario_codigo IS NULL)",
            name="ck_conversacion_tipo_propietario",
        ),
        Index(
            "uq_conversacion_individual", "proyecto_id", "propietario_codigo",
            unique=True, postgresql_where=text("tipo = 'individual'"),
        ),
        Index(
            "uq_conversacion_grupal", "proyecto_id", unique=True,
            postgresql_where=text("tipo = 'grupal'"),
        ),
        {"schema": "diagramas"},
    )

    id = Column(BigInteger, Identity(), primary_key=True)
    proyecto_id = Column(
        Integer,
        ForeignKey("diagramas.proyecto.id", onupdate="CASCADE", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    tipo = Column(String(15), nullable=False)
    propietario_codigo = Column(
        String(150),
        ForeignKey("Usuario.usuarios.codigo", onupdate="CASCADE", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    creado_en = Column(DateTime(timezone=True), nullable=False, server_default=func.now())




class Mensaje(Base):
    __tablename__ = "mensajes"
    __table_args__ = (
        CheckConstraint(
            "(rol = 'user' AND autor_codigo IS NOT NULL) OR "
            "(rol = 'assistant' AND autor_codigo IS NULL)",
            name="ck_mensaje_rol_autor",
        ),
        CheckConstraint("length(trim(texto)) > 0", name="ck_mensaje_texto"),
        Index("ix_mensajes_conversacion_id", "conversacion_id", "id"),
        {"schema": "diagramas"},
    )

    id = Column(BigInteger, Identity(), primary_key=True)
    conversacion_id = Column(
        BigInteger, ForeignKey("diagramas.conversaciones.id", ondelete="CASCADE"),
        nullable=False,
    )
    diagrama_id = Column(
        Integer, ForeignKey("diagramas.diagrama.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    rol = Column(String(15), nullable=False)
    autor_codigo = Column(
        String(150),
        ForeignKey("Usuario.usuarios.codigo", onupdate="CASCADE", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    # Preserve the displayed name at the time of the message.
    autor_nombre = Column(String(250), nullable=False)
    texto = Column(Text, nullable=False)
    # Reserved for trusted AI integration, never accepted by the public POST.
    resultado_ia = Column(JSONB, nullable=True)
    creado_en = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


ai_reply_index = Index(
    "uq_mensaje_respuesta_ia", Mensaje.conversacion_id,
    Mensaje.resultado_ia["reply_to"].astext, unique=True,
    postgresql_where=text("rol = 'assistant' AND resultado_ia ? 'reply_to'"),
)
