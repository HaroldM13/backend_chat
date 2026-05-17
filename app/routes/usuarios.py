"""
Endpoints de gestión de usuarios/perfil: ver, editar, subir foto, eliminar, buscar, presencia.
"""
import io
import uuid
import pathlib
from typing import Optional
from fastapi import APIRouter, HTTPException, status, Request, Depends, UploadFile, File
from bson import ObjectId
from pydantic import BaseModel, Field
from PIL import Image
from app.middleware.auth_middleware import obtener_usuario_actual
from app.services.log_service import registrar_log
from app.services.redis_service import obtener_ultima_vez
from app.websocket.manager import manager
from app.database import get_db

router = APIRouter(prefix="/usuarios", tags=["Usuarios"])

UPLOADS_PERFILES = pathlib.Path("uploads/perfiles")


class EditarPerfilSchema(BaseModel):
    nombre: Optional[str] = Field(None, min_length=2, max_length=50)
    descripcion: Optional[str] = Field(None, max_length=100)


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
        "foto_url": usuario.get("foto_url"),
        "descripcion": usuario.get("descripcion"),
        "created_at": usuario["created_at"],
    }


@router.patch("/perfil", summary="Editar nombre y/o descripción del perfil")
async def editar_perfil(
    datos: EditarPerfilSchema,
    usuario_actual: dict = Depends(obtener_usuario_actual)
):
    db = get_db()
    usuario_id = usuario_actual["sub"]
    campos: dict = {}
    if datos.nombre is not None:
        campos["nombre"] = datos.nombre.strip()
    if datos.descripcion is not None:
        campos["descripcion"] = datos.descripcion.strip()
    if not campos:
        raise HTTPException(status_code=400, detail="No hay campos para actualizar")
    await db.usuarios.update_one({"_id": ObjectId(usuario_id)}, {"$set": campos})
    return {"mensaje": "Perfil actualizado", **campos}


@router.post("/perfil/foto", summary="Subir o actualizar foto de perfil")
async def subir_foto_perfil(
    archivo: UploadFile = File(...),
    usuario_actual: dict = Depends(obtener_usuario_actual)
):
    if not archivo.content_type or not archivo.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Solo se permiten imágenes")
    datos = await archivo.read()
    try:
        img = Image.open(io.BytesIO(datos)).convert("RGB")
        img = img.resize((200, 200), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85, optimize=True)
        datos_comprimidos = buf.getvalue()
    except Exception:
        raise HTTPException(status_code=400, detail="Imagen inválida o corrupta")

    nombre_archivo = f"{uuid.uuid4().hex}.jpg"
    ruta = UPLOADS_PERFILES / nombre_archivo
    ruta.write_bytes(datos_comprimidos)
    foto_url = f"/uploads/perfiles/{nombre_archivo}"

    db = get_db()
    usuario_id = usuario_actual["sub"]
    usuario = await db.usuarios.find_one({"_id": ObjectId(usuario_id)})
    if usuario and usuario.get("foto_url"):
        pathlib.Path(usuario["foto_url"].lstrip("/")).unlink(missing_ok=True)

    await db.usuarios.update_one({"_id": ObjectId(usuario_id)}, {"$set": {"foto_url": foto_url}})
    return {"foto_url": foto_url}


@router.delete("/perfil", status_code=status.HTTP_200_OK, summary="Eliminar perfil propio")
async def eliminar_perfil(
    request: Request,
    usuario_actual: dict = Depends(obtener_usuario_actual)
):
    db = get_db()
    ip = request.client.host if request.client else "desconocida"
    usuario_id = usuario_actual["sub"]

    usuario = await db.usuarios.find_one({"_id": ObjectId(usuario_id)})
    if usuario and usuario.get("foto_url"):
        pathlib.Path(usuario["foto_url"].lstrip("/")).unlink(missing_ok=True)

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


@router.get("/{usuario_id}/presencia", summary="Consultar estado de conexión y última vez visto")
async def ver_presencia(
    usuario_id: str,
    usuario_actual: dict = Depends(obtener_usuario_actual)
):
    conectado = await manager.esta_conectado(usuario_id)
    ultima_vez = None if conectado else await obtener_ultima_vez(usuario_id)
    return {
        "conectado": conectado,
        "usuario_id": usuario_id,
        "ultima_vez": ultima_vez,
    }


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
        "telefono": usuario["telefono"],
    }
