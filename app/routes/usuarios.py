"""
Endpoints de gestión de usuarios/perfil: ver, editar nombre, eliminar, buscar, presencia.
"""
from fastapi import APIRouter, HTTPException, status, Request, Depends, Body
from bson import ObjectId
from pydantic import BaseModel, Field
from app.middleware.auth_middleware import obtener_usuario_actual
from app.services.log_service import registrar_log
from app.websocket.manager import manager
from app.database import get_db

router = APIRouter(prefix="/usuarios", tags=["Usuarios"])


class EditarNombreSchema(BaseModel):
    nombre: str = Field(..., min_length=2, max_length=50, description="Nuevo nombre del usuario")


@router.get("/perfil", summary="Ver perfil propio")
async def ver_perfil(usuario_actual: dict = Depends(obtener_usuario_actual)):
    db = get_db()
    usuario = await db.usuarios.find_one({"_id": ObjectId(usuario_actual["sub"])})
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return {
        "id": str(usuario["_id"]),
        "nombre": usuario["nombre"],
        "telefono": usuario["telefono"],
        "created_at": usuario["created_at"]
    }


@router.patch(
    "/perfil",
    summary="Editar nombre",
    description="Actualiza el nombre visible del usuario autenticado."
)
async def editar_nombre(
    datos: EditarNombreSchema,
    usuario_actual: dict = Depends(obtener_usuario_actual)
):
    """Edita el nombre del usuario."""
    db = get_db()
    usuario_id = usuario_actual["sub"]
    await db.usuarios.update_one(
        {"_id": ObjectId(usuario_id)},
        {"$set": {"nombre": datos.nombre.strip()}}
    )
    return {"mensaje": "Nombre actualizado", "nombre": datos.nombre.strip()}


@router.delete(
    "/perfil",
    status_code=status.HTTP_200_OK,
    summary="Eliminar perfil propio",
    description="Elimina la cuenta y todos sus datos asociados en cascada."
)
async def eliminar_perfil(
    request: Request,
    usuario_actual: dict = Depends(obtener_usuario_actual)
):
    db = get_db()
    ip = request.client.host if request.client else "desconocida"
    usuario_id = usuario_actual["sub"]

    await db.mensajes.delete_many({"remitente_id": usuario_id})
    await db.grupos.update_many({"miembros": usuario_id}, {"$pull": {"miembros": usuario_id}})

    grupos_propios = await db.grupos.find({"creador_id": usuario_id}).to_list(length=None)
    for grupo in grupos_propios:
        await db.mensajes.delete_many({"grupo_id": str(grupo["_id"])})
        await db.grupos.delete_one({"_id": grupo["_id"]})

    await db.contactos.delete_many({"usuario_id": usuario_id})
    await db.contactos.delete_many({"contacto_id": usuario_id})
    await db.sesiones.update_many({"usuario_id": usuario_id}, {"$set": {"activo": False}})
    await db.usuarios.delete_one({"_id": ObjectId(usuario_id)})

    await registrar_log("USER_DELETED", "success", ip, usuario_id,
                        {"mensaje": "Perfil eliminado con todos sus datos"})
    return {"mensaje": "Perfil eliminado exitosamente"}


@router.get(
    "/{usuario_id}/presencia",
    summary="Consultar estado de conexión",
    description="Retorna si el usuario tiene una sesión WebSocket activa en este momento."
)
async def ver_presencia(
    usuario_id: str,
    usuario_actual: dict = Depends(obtener_usuario_actual)
):
    """Consulta si un usuario está conectado actualmente."""
    return {"conectado": await manager.esta_conectado(usuario_id), "usuario_id": usuario_id}


@router.get("/buscar/{telefono}", summary="Buscar usuario por teléfono")
async def buscar_por_telefono(
    telefono: str,
    usuario_actual: dict = Depends(obtener_usuario_actual)
):
    db = get_db()
    usuario = await db.usuarios.find_one({"telefono": telefono})
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return {
        "id": str(usuario["_id"]),
        "nombre": usuario["nombre"],
        "telefono": usuario["telefono"]
    }
