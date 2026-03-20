"""
Endpoints de gestión de grupos de chat.
"""
from fastapi import APIRouter, HTTPException, status, Request, Depends
from bson import ObjectId
from app.schemas.grupo import CrearGrupoSchema, AgregarMiembroSchema
from app.models.grupo import GrupoModel
from app.middleware.auth_middleware import obtener_usuario_actual
from app.services.log_service import registrar_log
from app.database import get_db

router = APIRouter(prefix="/grupos", tags=["Grupos"])


def _grupo_a_respuesta(grupo: dict, miembros_info: list) -> dict:
    """Convierte un documento de grupo a formato de respuesta."""
    return {
        "id": str(grupo["_id"]),
        "nombre": grupo["nombre"],
        "creador_id": grupo["creador_id"],
        "miembros": miembros_info,
        "created_at": grupo["created_at"]
    }


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Crear grupo",
    description="Crea un nuevo grupo con el nombre indicado. El creador queda como primer miembro."
)
async def crear_grupo(
    datos: CrearGrupoSchema,
    request: Request,
    usuario_actual: dict = Depends(obtener_usuario_actual)
):
    """Crea un nuevo grupo de chat."""
    db = get_db()
    ip = request.client.host if request.client else "desconocida"
    usuario_id = usuario_actual["sub"]

    # El creador es automáticamente el primer miembro
    doc = GrupoModel.nuevo(datos.nombre, usuario_id, [usuario_id])
    resultado = await db.grupos.insert_one(doc)
    grupo_id = str(resultado.inserted_id)

    # Obtener info del creador para la respuesta
    creador = await db.usuarios.find_one({"_id": ObjectId(usuario_id)})
    miembros_info = [{
        "id": usuario_id,
        "nombre": creador["nombre"],
        "telefono": creador["telefono"]
    }]

    # Auditoría
    await registrar_log(
        action="GROUP_CREATED",
        status="success",
        ip=ip,
        user_id=usuario_id,
        details={"grupo_id": grupo_id, "nombre": datos.nombre}
    )

    return _grupo_a_respuesta(doc | {"_id": ObjectId(grupo_id)}, miembros_info)


@router.get(
    "",
    summary="Listar grupos del usuario",
    description="Retorna todos los grupos donde el usuario autenticado es miembro."
)
async def listar_grupos(usuario_actual: dict = Depends(obtener_usuario_actual)):
    """Lista todos los grupos del usuario."""
    db = get_db()
    usuario_id = usuario_actual["sub"]

    grupos = await db.grupos.find({"miembros": usuario_id}).to_list(length=None)
    resultado = []

    for grupo in grupos:
        miembros_info = []
        for mid in grupo["miembros"]:
            m = await db.usuarios.find_one({"_id": ObjectId(mid)})
            if m:
                miembros_info.append({
                    "id": mid,
                    "nombre": m["nombre"],
                    "telefono": m["telefono"]
                })
        resultado.append(_grupo_a_respuesta(grupo, miembros_info))

    return resultado


@router.get(
    "/{grupo_id}",
    summary="Ver detalle de un grupo",
    description="Retorna los detalles de un grupo, incluyendo sus miembros."
)
async def ver_grupo(
    grupo_id: str,
    usuario_actual: dict = Depends(obtener_usuario_actual)
):
    """Retorna el detalle de un grupo."""
    db = get_db()
    usuario_id = usuario_actual["sub"]

    try:
        grupo = await db.grupos.find_one({"_id": ObjectId(grupo_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="ID de grupo inválido")

    if not grupo:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")

    # Solo los miembros pueden ver el grupo
    if usuario_id not in grupo["miembros"]:
        raise HTTPException(status_code=403, detail="No eres miembro de este grupo")

    miembros_info = []
    for mid in grupo["miembros"]:
        m = await db.usuarios.find_one({"_id": ObjectId(mid)})
        if m:
            miembros_info.append({
                "id": mid,
                "nombre": m["nombre"],
                "telefono": m["telefono"]
            })

    return _grupo_a_respuesta(grupo, miembros_info)


@router.post(
    "/{grupo_id}/miembros",
    status_code=status.HTTP_201_CREATED,
    summary="Agregar miembro al grupo",
    description="Agrega un usuario al grupo buscándolo por teléfono. Solo miembros pueden agregar."
)
async def agregar_miembro(
    grupo_id: str,
    datos: AgregarMiembroSchema,
    request: Request,
    usuario_actual: dict = Depends(obtener_usuario_actual)
):
    """Agrega un miembro al grupo por teléfono."""
    db = get_db()
    ip = request.client.host if request.client else "desconocida"
    usuario_id = usuario_actual["sub"]

    try:
        grupo = await db.grupos.find_one({"_id": ObjectId(grupo_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="ID de grupo inválido")

    if not grupo:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")

    if usuario_id not in grupo["miembros"]:
        raise HTTPException(status_code=403, detail="No eres miembro de este grupo")

    # Buscar al nuevo miembro por teléfono
    nuevo_miembro = await db.usuarios.find_one({"telefono": datos.telefono})
    if not nuevo_miembro:
        raise HTTPException(status_code=404, detail="Usuario no encontrado con ese teléfono")

    nuevo_miembro_id = str(nuevo_miembro["_id"])

    if nuevo_miembro_id in grupo["miembros"]:
        raise HTTPException(status_code=409, detail="El usuario ya es miembro del grupo")

    # Agregar al grupo
    await db.grupos.update_one(
        {"_id": ObjectId(grupo_id)},
        {"$push": {"miembros": nuevo_miembro_id}}
    )

    # Auditoría
    await registrar_log(
        action="GROUP_MEMBER_ADDED",
        status="success",
        ip=ip,
        user_id=usuario_id,
        details={"grupo_id": grupo_id, "nuevo_miembro_id": nuevo_miembro_id}
    )

    return {
        "mensaje": "Miembro agregado exitosamente",
        "miembro": {
            "id": nuevo_miembro_id,
            "nombre": nuevo_miembro["nombre"],
            "telefono": nuevo_miembro["telefono"]
        }
    }


@router.delete(
    "/{grupo_id}",
    status_code=status.HTTP_200_OK,
    summary="Eliminar grupo",
    description="Elimina el grupo y todos sus mensajes. Solo el creador puede hacerlo."
)
async def eliminar_grupo(
    grupo_id: str,
    request: Request,
    usuario_actual: dict = Depends(obtener_usuario_actual)
):
    """Elimina un grupo (solo el creador)."""
    db = get_db()
    ip = request.client.host if request.client else "desconocida"
    usuario_id = usuario_actual["sub"]

    try:
        grupo = await db.grupos.find_one({"_id": ObjectId(grupo_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="ID de grupo inválido")

    if not grupo:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")

    if grupo["creador_id"] != usuario_id:
        raise HTTPException(status_code=403, detail="Solo el creador puede eliminar el grupo")

    # Eliminar mensajes del grupo
    await db.mensajes.delete_many({"grupo_id": grupo_id})

    # Eliminar el grupo
    await db.grupos.delete_one({"_id": ObjectId(grupo_id)})

    # Auditoría
    await registrar_log(
        action="GROUP_DELETED",
        status="success",
        ip=ip,
        user_id=usuario_id,
        details={"grupo_id": grupo_id, "nombre": grupo["nombre"]}
    )

    return {"mensaje": "Grupo eliminado exitosamente"}


@router.post(
    "/{grupo_id}/salir",
    status_code=status.HTTP_200_OK,
    summary="Salir de un grupo",
    description="El usuario autenticado abandona el grupo. El creador no puede salir sin eliminar."
)
async def salir_grupo(
    grupo_id: str,
    request: Request,
    usuario_actual: dict = Depends(obtener_usuario_actual)
):
    """El usuario sale del grupo."""
    db = get_db()
    ip = request.client.host if request.client else "desconocida"
    usuario_id = usuario_actual["sub"]

    try:
        grupo = await db.grupos.find_one({"_id": ObjectId(grupo_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="ID de grupo inválido")

    if not grupo:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")

    if usuario_id not in grupo["miembros"]:
        raise HTTPException(status_code=400, detail="No eres miembro de este grupo")

    if grupo["creador_id"] == usuario_id:
        raise HTTPException(
            status_code=400,
            detail="Eres el creador del grupo. Elimínalo o transfiere la administración."
        )

    # Remover al usuario del grupo
    await db.grupos.update_one(
        {"_id": ObjectId(grupo_id)},
        {"$pull": {"miembros": usuario_id}}
    )

    # Auditoría
    await registrar_log(
        action="GROUP_LEFT",
        status="success",
        ip=ip,
        user_id=usuario_id,
        details={"grupo_id": grupo_id, "nombre": grupo["nombre"]}
    )

    return {"mensaje": "Saliste del grupo exitosamente"}
