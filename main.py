"""
Punto de entrada principal de JHT Chat API.
Configura FastAPI, CORS, ciclo de vida de la app y registra todos los routers.
"""
import os
import asyncio
import pathlib
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

from app.database import conectar_db, cerrar_db
from app.services.redis_service import conectar_redis, cerrar_redis
from app.services.rabbit_service import conectar_rabbit, cerrar_rabbit, iniciar_consumer
from app.routes.auth import router as router_auth
from app.routes.usuarios import router as router_usuarios
from app.routes.contactos import router as router_contactos
from app.routes.grupos import router as router_grupos
from app.routes.mensajes import router as router_mensajes
from app.routes.websocket_routes import router as router_ws
from app.routes.estados import router as router_estados

load_dotenv()

# Orígenes permitidos para CORS (desde .env o valor por defecto)
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:5173,http://localhost:3000"
    ).split(",")
]


async def _limpiar_estados_expirados() -> None:
    """Elimina estados expirados (doc + imagen) cada 60 segundos."""
    from app.database import get_db
    while True:
        await asyncio.sleep(60)
        try:
            db = get_db()
            ahora = datetime.now(timezone.utc)
            expirados = await db.estados.find(
                {"expira_at": {"$lte": ahora}}
            ).to_list(length=None)
            for estado in expirados:
                ruta = pathlib.Path(estado["url_imagen"].lstrip("/"))
                ruta.unlink(missing_ok=True)
            if expirados:
                await db.estados.delete_many({"expira_at": {"$lte": ahora}})
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Gestiona el ciclo de vida de la aplicación:
    - Al iniciar: conecta a MongoDB, Redis y RabbitMQ; lanza el consumer
    - Al apagar: cierra todas las conexiones en orden inverso
    """
    pathlib.Path("uploads/chat").mkdir(parents=True, exist_ok=True)
    pathlib.Path("uploads/estados").mkdir(parents=True, exist_ok=True)
    tarea_limpieza = asyncio.create_task(_limpiar_estados_expirados())
    await conectar_db()
    await conectar_redis()
    print("Conectado a Redis")
    await conectar_rabbit()
    await iniciar_consumer()
    print("Conectado a RabbitMQ y consumer activo")
    yield
    tarea_limpieza.cancel()
    await cerrar_rabbit()
    await cerrar_redis()
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

# Servir archivos subidos (imágenes de chat y estados)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Registro de todos los routers
app.include_router(router_auth)
app.include_router(router_usuarios)
app.include_router(router_contactos)
app.include_router(router_grupos)
app.include_router(router_mensajes)
app.include_router(router_ws)
app.include_router(router_estados)


@app.get("/", tags=["Estado"])
async def raiz():
    """Endpoint de bienvenida para verificar que la API está activa."""
    return {
        "app": "JHT Chat API",
        "version": "1.0.0",
        "estado": "activo",
        "docs": "/docs"
    }
