"""
Punto de entrada principal de JHT Chat API.
Configura FastAPI, CORS, ciclo de vida de la app y registra todos los routers.
"""
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from app.database import conectar_db, cerrar_db
from app.routes.auth import router as router_auth
from app.routes.usuarios import router as router_usuarios
from app.routes.contactos import router as router_contactos
from app.routes.grupos import router as router_grupos
from app.routes.mensajes import router as router_mensajes
from app.routes.websocket_routes import router as router_ws

load_dotenv()

# Orígenes permitidos para CORS (desde .env o valor por defecto)
ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:5173,http://localhost:3000"
).split(",")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Gestiona el ciclo de vida de la aplicación:
    - Al iniciar: conecta a MongoDB
    - Al apagar: cierra la conexión
    """
    await conectar_db()
    yield
    await cerrar_db()


# Instancia principal de FastAPI con metadatos para Swagger
app = FastAPI(
    title="JHT Chat API",
    description=(
        "API REST y WebSocket para el sistema de chat JHT Chat. "
        "Permite registro/login de usuarios, mensajería en tiempo real "
        "(sala general, privada y grupal), gestión de contactos y grupos, "
        "con auditoría completa de acciones."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",      # Swagger UI
    redoc_url="/redoc"     # ReDoc
)

# Configuración de CORS para permitir peticiones desde el frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Registro de todos los routers
app.include_router(router_auth)
app.include_router(router_usuarios)
app.include_router(router_contactos)
app.include_router(router_grupos)
app.include_router(router_mensajes)
app.include_router(router_ws)


@app.get("/", tags=["Estado"])
async def raiz():
    """Endpoint de bienvenida para verificar que la API está activa."""
    return {
        "app": "JHT Chat API",
        "version": "1.0.0",
        "estado": "activo",
        "docs": "/docs"
    }
