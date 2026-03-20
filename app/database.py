"""
Conexión a MongoDB usando Motor (driver async).
Motor permite operaciones no bloqueantes compatibles con asyncio/FastAPI.
"""
import os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

# URI y nombre de la base de datos desde variables de entorno
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
DATABASE_NAME = os.getenv("DATABASE_NAME", "jht_chat")

# Cliente global de Motor (se inicializa una sola vez al arrancar la app)
client: AsyncIOMotorClient = None
db = None


async def conectar_db():
    """Inicializa la conexión a MongoDB al arrancar la aplicación."""
    global client, db
    client = AsyncIOMotorClient(MONGODB_URI)
    db = client[DATABASE_NAME]
    # Crear índices únicos necesarios
    await db.usuarios.create_index("telefono", unique=True)
    await db.sesiones.create_index("token")
    await db.logs.create_index("created_at")
    print(f"Conectado a MongoDB: {DATABASE_NAME}")


async def cerrar_db():
    """Cierra la conexión a MongoDB al apagar la aplicación."""
    global client
    if client:
        client.close()
        print("Conexión a MongoDB cerrada")


def get_db():
    """Retorna la instancia de la base de datos para usar en los endpoints."""
    return db
