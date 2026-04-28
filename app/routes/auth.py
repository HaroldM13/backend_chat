"""
Endpoints de autenticación: registro, login y logout.
"""
from fastapi import APIRouter, HTTPException, status, Request, Depends
from app.schemas.auth import EnviarOTPSchema, RegistroSchema, LoginSchema, TokenSchema
from app.models.usuario import UsuarioModel
from app.models.sesion import SesionModel
from app.services.auth_service import crear_token, invalidar_sesion
from app.services.redis_service import cachear_sesion
from app.services.twilio_service import enviar_otp, verificar_otp
from app.services.log_service import registrar_log
from app.middleware.auth_middleware import obtener_usuario_actual
from app.database import get_db

router = APIRouter(prefix="/auth", tags=["Autenticación"])


@router.post(
    "/enviar-otp",
    status_code=status.HTTP_200_OK,
    summary="Enviar código OTP por SMS",
    description="Envía un código de verificación al número de teléfono indicado."
)
async def enviar_codigo(datos: EnviarOTPSchema, request: Request):
    """Envía un OTP via Twilio Verify al teléfono del usuario."""
    db = get_db()
    ip = request.client.host if request.client else "desconocida"

    # Verificar si el teléfono ya está registrado antes de gastar el SMS
    existente = await db.usuarios.find_one({"telefono": datos.telefono})
    if existente:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El número de teléfono ya está registrado"
        )

    try:
        await enviar_otp(datos.telefono)
        await registrar_log("OTP_SENT", "success", ip,
                            details={"telefono": datos.telefono})
        return {"mensaje": "Código enviado"}
    except Exception:
        await registrar_log("OTP_SENT", "error", ip,
                            details={"telefono": datos.telefono})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No se pudo enviar el código. Intenta de nuevo."
        )


@router.post(
    "/registro",
    response_model=TokenSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar nuevo usuario",
    description="Crea un usuario con nombre y teléfono. El teléfono debe ser único."
)
async def registro(datos: RegistroSchema, request: Request):
    """Registra un nuevo usuario verificando el código OTP primero."""
    db = get_db()
    ip = request.client.host if request.client else "desconocida"

    # Verificar OTP solo si el usuario eligió verificar por SMS
    if datos.codigo:
        otp_valido = await verificar_otp(datos.telefono, datos.codigo)
        if not otp_valido:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Código incorrecto o expirado"
            )

    # Verificar que el teléfono no esté registrado
    existente = await db.usuarios.find_one({"telefono": datos.telefono})
    if existente:
        await registrar_log(
            action="USER_REGISTER",
            status="error",
            ip=ip,
            details={"telefono": datos.telefono, "motivo": "teléfono ya registrado"}
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El número de teléfono ya está registrado"
        )

    # Insertar usuario
    doc_usuario = UsuarioModel.nuevo(datos.telefono, datos.nombre)
    resultado = await db.usuarios.insert_one(doc_usuario)
    usuario_id = str(resultado.inserted_id)

    # Generar token JWT
    token = crear_token({"sub": usuario_id, "telefono": datos.telefono})

    # Guardar sesión activa en MongoDB y cachear en Redis
    doc_sesion = SesionModel.nueva(usuario_id, token)
    await db.sesiones.insert_one(doc_sesion)
    await cachear_sesion(token)

    # Auditoría
    await registrar_log(
        action="USER_REGISTER",
        status="success",
        ip=ip,
        user_id=usuario_id,
        details={"nombre": datos.nombre, "telefono": datos.telefono}
    )

    return TokenSchema(
        access_token=token,
        usuario_id=usuario_id,
        nombre=datos.nombre
    )


@router.post(
    "/login",
    response_model=TokenSchema,
    summary="Iniciar sesión",
    description="Autentica al usuario por número de teléfono y retorna un JWT."
)
async def login(datos: LoginSchema, request: Request):
    """Inicia sesión verificando el código OTP primero."""
    db = get_db()
    ip = request.client.host if request.client else "desconocida"

    # Buscar usuario por teléfono
    usuario = await db.usuarios.find_one({"telefono": datos.telefono})
    if not usuario:
        await registrar_log(
            action="USER_LOGIN",
            status="error",
            ip=ip,
            details={"telefono": datos.telefono, "motivo": "usuario no encontrado"}
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Número de teléfono no registrado"
        )

    usuario_id = str(usuario["_id"])

    # Generar nuevo token
    token = crear_token({"sub": usuario_id, "telefono": datos.telefono})

    # Guardar sesión activa en MongoDB y cachear en Redis
    doc_sesion = SesionModel.nueva(usuario_id, token)
    await db.sesiones.insert_one(doc_sesion)
    await cachear_sesion(token)

    # Auditoría
    await registrar_log(
        action="USER_LOGIN",
        status="success",
        ip=ip,
        user_id=usuario_id,
        details={"telefono": datos.telefono}
    )

    return TokenSchema(
        access_token=token,
        usuario_id=usuario_id,
        nombre=usuario["nombre"]
    )


@router.post(
    "/logout",
    status_code=status.HTTP_200_OK,
    summary="Cerrar sesión",
    description="Invalida el JWT actual del usuario en la base de datos."
)
async def logout(request: Request, usuario_actual: dict = Depends(obtener_usuario_actual)):
    """Cierra la sesión invalidando el token JWT."""
    ip = request.client.host if request.client else "desconocida"
    token = usuario_actual["_token"]
    usuario_id = usuario_actual["sub"]

    # Invalidar la sesión en MongoDB
    await invalidar_sesion(token)

    # Auditoría
    await registrar_log(
        action="USER_LOGOUT",
        status="success",
        ip=ip,
        user_id=usuario_id
    )

    return {"mensaje": "Sesión cerrada exitosamente"}
