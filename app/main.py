from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import models
from app.database import Base, engine, ensure_version_historial_columns, ensure_proyecto_invitation_columns
from app.routers.auth import router as auth
from app.routers.comentario import router as comentario
from app.routers.diagrama import router as diagrama
from app.routers.import_export import router as import_export
from app.routers.proyecto import router as proyecto
from app.routers.realtime import router as realtime
from app.routers.usuario import router as usuario

Base.metadata.create_all(bind=engine)  # Crear las tablas en la base de datos
ensure_version_historial_columns()
ensure_proyecto_invitation_columns()


app = FastAPI(
    title="Backend Diagramador Colaborativo",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://frontend-copia-software.vercel.app"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth)
app.include_router(usuario)
app.include_router(proyecto)
app.include_router(diagrama)
app.include_router(comentario)
app.include_router(import_export)
app.include_router(realtime)


@app.get("/")
def inicio():
    return {"mensaje": "Backend corriendo y funcionando correctamente"}


@app.get("/health")
def health_check():
    return {"estado": "ok", "Base de datos": "conectada"}
