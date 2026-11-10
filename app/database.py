from sqlalchemy import create_engine, text
from  sqlalchemy.orm import declarative_base, sessionmaker
from app.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,  # Descarta conexiones cerradas antes de reutilizarlas.
    pool_recycle=300,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine) # se crea sseiones para consultar con la base de datos
Base = declarative_base() #base para crear modelos/tablas 


def ensure_version_historial_columns():
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                ALTER TABLE "diagramas".version_historial
                ADD COLUMN IF NOT EXISTS titulo varchar(150)
                """
            )
        )
        connection.execute(
            text(
                """
                ALTER TABLE "diagramas".version_historial
                ADD COLUMN IF NOT EXISTS descripcion text
                """
            )
        )
        connection.execute(
            text(
                """
                ALTER TABLE "diagramas".version_historial
                ADD COLUMN IF NOT EXISTS tipo varchar(50) DEFAULT 'auto'
                """
            )
        )
        connection.execute(
            text(
                """
                ALTER TABLE "diagramas".version_historial
                ADD COLUMN IF NOT EXISTS contenido_hash varchar(128)
                """
            )
        )


def ensure_proyecto_invitation_columns():
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                ALTER TABLE "diagramas".proyecto
                ADD COLUMN IF NOT EXISTS codigo_invitacion varchar(64) UNIQUE
                """
            )
        )
        connection.execute(
            text(
                """
                ALTER TABLE "diagramas".proyecto
                ADD COLUMN IF NOT EXISTS codigo_expira_en timestamp without time zone
                """
            )
        )


#se entrega la conexion a los endpoints
def get_db(): 
    db = SessionLocal()
    try: 
        yield db 
    finally: 
        db.close()

