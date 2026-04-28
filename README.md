# JHT Chat — Backend

API REST y WebSocket en tiempo real construida con **FastAPI**, respaldada por **MongoDB**, **Redis** y **RabbitMQ**. Provee autenticación sin contraseña, mensajería instantánea, envío de imágenes y estados (stories) con expiración automática.

---

## Tabla de contenidos

1. [Descripción general](#descripción-general)
2. [Arquitectura](#arquitectura)
3. [Stack tecnológico](#stack-tecnológico)
4. [Estructura del proyecto](#estructura-del-proyecto)
5. [Colecciones MongoDB](#colecciones-mongodb)
6. [API — Endpoints](#api--endpoints)
7. [WebSocket — Protocolo](#websocket--protocolo)
8. [Servicios internos](#servicios-internos)
9. [Variables de entorno](#variables-de-entorno)
10. [Instalación y puesta en marcha](#instalación-y-puesta-en-marcha)
11. [Despliegue en producción](#despliegue-en-producción)
12. [Flujos principales](#flujos-principales)

---

## Descripción general

JHT Chat es una aplicación de mensajería en tiempo real. El backend expone:

- **API REST** para autenticación, gestión de usuarios, contactos, grupos, mensajes e imágenes.
- **Endpoints WebSocket** para mensajería instantánea en sala general, chats privados y grupos.
- **Tareas en segundo plano** para limpieza automática de estados expirados.

La autenticación es sin contraseña: el usuario se registra e inicia sesión únicamente con su número de teléfono. El registro opcionalmente puede verificar el número via SMS (Twilio Verify).

---

## Arquitectura

```
                         ┌────────────────────┐
                         │   Cliente (React)   │
                         └────────┬───────────┘
                                  │  HTTP / WebSocket
                         ┌────────▼───────────┐
                         │      FastAPI        │
                         │  (uvicorn, :8000)   │
                         └──┬──────┬──────┬───┘
                            │      │      │
              ┌─────────────┘      │      └──────────────┐
              │                    │                     │
    ┌─────────▼────────┐  ┌────────▼───────┐  ┌─────────▼───────┐
    │     MongoDB       │  │     Redis      │  │    RabbitMQ     │
    │  (persistencia)   │  │  (cache /      │  │  (mensajería    │
    │                   │  │   presencia)   │  │   en cola)      │
    └──────────────────┘  └────────────────┘  └─────────────────┘
```

### Rol de cada componente

| Componente | Rol |
|---|---|
| **FastAPI** | Maneja requests HTTP y conexiones WebSocket. Valida esquemas con Pydantic. |
| **MongoDB** | Persistencia de todos los datos: usuarios, mensajes, grupos, sesiones, logs. |
| **Redis** | Cache de sesiones JWT (evita consultar MongoDB en cada request) y tracking de presencia en línea. |
| **RabbitMQ** | Desacopla la recepción de mensajes del broadcast. El WS handler publica; un consumer distribuye a todos los clientes conectados. |
| **Twilio Verify** | Envío y verificación de OTP por SMS para el registro con doble verificación (opcional). |
| **Pillow** | Compresión y redimensionado de imágenes antes de guardarlas en disco. |

### Flujo de un mensaje de chat

```
1. Cliente envía mensaje vía WebSocket
2. WS handler lo valida y guarda en MongoDB
3. Handler llama publicar_mensaje() → publica en RabbitMQ (exchange FANOUT)
4. Consumer on_mensaje() recibe el evento
5. manager.broadcast() reenvía a TODOS los clientes conectados a esa sala
```

### Cache de sesiones con Redis

```
Login exitoso
  → token guardado en MongoDB (colección sesiones)
  → token cacheado en Redis: SET sesion:{token} "1" EX 86400

Cada request autenticado
  → GET sesion:{token} en Redis   ← microsegundos, sin tocar MongoDB

Logout
  → DELETE sesion:{token} en Redis
  → marcar inactivo en MongoDB
```

### Presencia en línea

```
Abre WebSocket   → INCR presencia:{usuario_id}   → contador sube
Cierra pestaña   → DECR presencia:{usuario_id}   → contador baja
Llega a 0        → DELETE presencia:{usuario_id} → usuario offline
```

Las operaciones INCR/DECR de Redis son atómicas: sin condiciones de carrera aunque el usuario tenga varias pestañas abiertas simultáneamente.

### Topología RabbitMQ

```
WS Handler
    │
    └─► publicar_mensaje()
              │
              ▼
    Exchange "chat_mensajes" (FANOUT, durable)
              │
    ┌─────────┘
    │
    ▼
Cola anónima/exclusiva (por instancia del backend)
    │
    ▼
Consumer on_mensaje()
    │
    ▼
manager.broadcast() → todos los clientes WebSocket de la sala
```

---

## Stack tecnológico

| Tecnología | Versión | Uso |
|---|---|---|
| Python | 3.10+ | Lenguaje base |
| FastAPI | 0.111+ | Framework web / WebSockets |
| Motor | 3.x | Driver async para MongoDB |
| Redis (`redis[asyncio]`) | 5.x | Cache de sesiones y presencia |
| aio-pika | 9.x | Cliente async para RabbitMQ |
| PyJWT | 2.x | Generación y validación de tokens JWT |
| Pillow | 10.x | Compresión de imágenes |
| Twilio | 9.x | Envío de OTP por SMS |
| uvicorn | 0.29+ | Servidor ASGI |
| python-dotenv | 1.x | Carga de variables de entorno |
| python-multipart | — | Soporte para subida de archivos (multipart/form-data) |

---

## Estructura del proyecto

```
backend_chat/
├── main.py                        # Entry point: app FastAPI, lifespan, rutas, static files
├── requirements.txt               # Dependencias Python
├── .env                           # Variables de entorno (NO subir a git)
├── .env.example                   # Plantilla de variables de entorno
├── uploads/
│   ├── chat/                      # Imágenes de mensajes (servidas en /uploads/chat/)
│   └── estados/                   # Imágenes de estados/stories (servidas en /uploads/estados/)
└── app/
    ├── database.py                # Conexión async a MongoDB con Motor
    ├── middleware/
    │   └── auth_middleware.py     # Dependency: extrae y valida JWT en cada request protegido
    ├── models/                    # Documentos MongoDB (factory methods, sin ORM)
    │   ├── usuario.py             # UsuarioModel.nuevo(telefono, nombre)
    │   ├── contacto.py            # ContactoModel.nuevo(usuario_id, contacto_id)
    │   ├── grupo.py               # GrupoModel.nuevo(nombre, creador_id, miembros)
    │   ├── mensaje.py             # MensajeModel.nuevo(tipo, subtipo, remitente_id, ...)
    │   ├── sesion.py              # SesionModel.nueva(usuario_id, token)
    │   ├── estado.py              # EstadoModel.nuevo(usuario_id, nombre_usuario, url) → expira en 5 min
    │   └── log.py                 # LogModel.nuevo(accion, resultado, ip, ...)
    ├── schemas/                   # Esquemas Pydantic (validación de entrada/salida)
    │   ├── auth.py                # EnviarOTPSchema, RegistroSchema, LoginSchema, TokenSchema
    │   ├── usuario.py             # EditarNombreSchema
    │   ├── contacto.py            # AgregarContactoSchema
    │   ├── grupo.py               # CrearGrupoSchema, AgregarMiembroSchema
    │   └── mensaje.py             # MensajeSchema
    ├── routes/                    # Routers FastAPI (un archivo por recurso)
    │   ├── auth.py                # POST /auth/enviar-otp, /registro, /login, /logout
    │   ├── usuarios.py            # GET/PATCH/DELETE /usuarios/perfil, /buscar, /presencia
    │   ├── contactos.py           # GET/POST/DELETE /contactos y /contactos/{id}
    │   ├── grupos.py              # GET/POST /grupos, miembros, salir, eliminar
    │   ├── mensajes.py            # GET historial, POST imagen, POST leer, DELETE chat
    │   ├── estados.py             # GET/POST/DELETE /estados
    │   └── websocket_routes.py    # WS /ws/sala, /ws/privado/{id}, /ws/grupo/{id}
    ├── services/                  # Lógica de negocio y conexiones a servicios externos
    │   ├── auth_service.py        # crear_token(), invalidar_sesion()
    │   ├── redis_service.py       # cachear_sesion(), verificar_sesion(), presencia INCR/DECR
    │   ├── rabbit_service.py      # publicar_mensaje(), iniciar_consumer(), on_mensaje()
    │   ├── twilio_service.py      # enviar_otp(), verificar_otp() via asyncio.to_thread()
    │   └── log_service.py         # registrar_log() — 14 tipos de eventos auditables
    └── websocket/
        └── manager.py             # ConnectionManager: dict de salas, broadcast, presencia Redis
```

---

## Colecciones MongoDB

Base de datos: `jht_chat`

### `usuarios`
```json
{
  "_id": "ObjectId",
  "nombre": "Juan Hernández",
  "telefono": "3001234567",
  "created_at": "2024-01-15T10:00:00Z"
}
```

### `sesiones`
```json
{
  "_id": "ObjectId",
  "token": "eyJhbGci...",
  "usuario_id": "string",
  "activo": true,
  "created_at": "2024-01-15T10:00:00Z"
}
```

### `mensajes`
```json
{
  "_id": "ObjectId",
  "tipo": "sala | privado | grupo",
  "subtipo": "texto | imagen",
  "remitente_id": "string",
  "contenido": "Hola! | /uploads/chat/uuid.jpg",
  "destinatario_id": "string (solo privado)",
  "grupo_id": "string (solo grupo)",
  "leido": false,
  "created_at": "2024-01-15T10:00:00Z"
}
```

### `contactos`
```json
{
  "_id": "ObjectId",
  "usuario_id": "string",
  "contacto_id": "string",
  "created_at": "2024-01-15T10:00:00Z"
}
```

### `grupos`
```json
{
  "_id": "ObjectId",
  "nombre": "Equipo dev",
  "creador_id": "string",
  "miembros": ["id1", "id2", "id3"],
  "created_at": "2024-01-15T10:00:00Z"
}
```

### `estados`
```json
{
  "_id": "ObjectId",
  "usuario_id": "string",
  "nombre_usuario": "Juan",
  "url_imagen": "/uploads/estados/uuid.jpg",
  "created_at": "2024-01-15T10:00:00Z",
  "expira_at": "2024-01-15T10:05:00Z"
}
```

> `expira_at = created_at + 5 minutos`. Una tarea en background elimina los documentos y archivos expirados cada 60 segundos.

### `logs`
```json
{
  "_id": "ObjectId",
  "accion": "USER_LOGIN",
  "resultado": "success | error",
  "ip": "192.168.1.1",
  "usuario_id": "string (opcional)",
  "detalles": { "telefono": "..." },
  "created_at": "2024-01-15T10:00:00Z"
}
```

**Tipos de acción registrados:** `USER_REGISTER`, `USER_LOGIN`, `USER_LOGOUT`, `OTP_SENT`, `CONTACT_ADD`, `CONTACT_DELETE`, `GROUP_CREATE`, `GROUP_JOIN`, `GROUP_LEAVE`, `GROUP_DELETE`, `MESSAGE_SEND`, `IMAGE_UPLOAD`, `ESTADO_UPLOAD`, `ESTADO_DELETE`

---

## API — Endpoints

Todos los endpoints marcados con `(*)` requieren el header de autenticación:
```
Authorization: Bearer <access_token>
```

### Autenticación

| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| `POST` | `/auth/enviar-otp` | No | Envía SMS con código OTP. Verifica que el teléfono NO esté registrado antes de gastar el SMS. |
| `POST` | `/auth/registro` | No | Registra nuevo usuario. Si `codigo` es no vacío, verifica OTP primero. |
| `POST` | `/auth/login` | No | Login directo por teléfono (sin OTP). |
| `POST` | `/auth/logout` | `(*)` | Invalida el token en Redis y MongoDB. |

**Body — `/auth/registro`:**
```json
{
  "nombre": "Juan",
  "telefono": "3001234567",
  "codigo": ""
}
```
Si `codigo` viene vacío → registro directo. Si viene con valor → verifica OTP con Twilio.

**Respuesta exitosa (registro / login):**
```json
{
  "access_token": "eyJhbGci...",
  "token_type": "bearer",
  "usuario_id": "abc123",
  "nombre": "Juan"
}
```

### Usuarios

| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| `GET` | `/usuarios/perfil` | `(*)` | Perfil del usuario autenticado |
| `PATCH` | `/usuarios/perfil` | `(*)` | Editar nombre |
| `DELETE` | `/usuarios/perfil` | `(*)` | Eliminar cuenta y todos sus datos |
| `GET` | `/usuarios/buscar/{telefono}` | `(*)` | Buscar usuario por número |
| `GET` | `/usuarios/{id}/presencia` | `(*)` | Verificar si el usuario está conectado (Redis) |

### Contactos

| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| `GET` | `/contactos` | `(*)` | Listar contactos del usuario |
| `POST` | `/contactos` | `(*)` | Agregar contacto por número de teléfono |
| `DELETE` | `/contactos/{id}` | `(*)` | Eliminar contacto y todos los mensajes privados con él |

### Grupos

| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| `GET` | `/grupos` | `(*)` | Listar grupos del usuario |
| `POST` | `/grupos` | `(*)` | Crear nuevo grupo |
| `GET` | `/grupos/{id}` | `(*)` | Detalle de un grupo |
| `POST` | `/grupos/{id}/miembros` | `(*)` | Agregar miembro (por número de teléfono) |
| `POST` | `/grupos/{id}/salir` | `(*)` | Salir del grupo |
| `DELETE` | `/grupos/{id}` | `(*)` | Eliminar grupo (solo el creador) |

### Mensajes

| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| `GET` | `/mensajes/sala?limite=50` | `(*)` | Historial sala general |
| `GET` | `/mensajes/privado/{id}?limite=50` | `(*)` | Historial chat privado |
| `GET` | `/mensajes/grupo/{id}?limite=50` | `(*)` | Historial de grupo |
| `POST` | `/mensajes/privado/{id}/leer` | `(*)` | Marcar mensajes como leídos |
| `DELETE` | `/mensajes/privado/{id}` | `(*)` | Eliminar conversación privada |
| `POST` | `/mensajes/imagen` | `(*)` | Subir imagen (multipart/form-data) |

**Form-data — `/mensajes/imagen`:**
```
archivo:          <File>           (requerido)
tipo_chat:        sala|privado|grupo (requerido)
destinatario_id:  <id>             (requerido si privado)
grupo_id:         <id>             (requerido si grupo)
```
La imagen es comprimida con Pillow (máx. 1200px, JPEG, calidad 75%) y guardada en `uploads/chat/`.

### Estados (Stories)

| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| `GET` | `/estados` | `(*)` | Lista estados propios y de contactos (no expirados) |
| `POST` | `/estados` | `(*)` | Sube imagen de estado (expira en 5 minutos) |
| `DELETE` | `/estados/{id}` | `(*)` | Elimina estado propio y su archivo del disco |

### Archivos estáticos

Las imágenes guardadas en disco son servidas directamente por FastAPI (`StaticFiles`):
```
GET /uploads/chat/{nombre}.jpg
GET /uploads/estados/{nombre}.jpg
```

---

## WebSocket — Protocolo

### Conexión

El token JWT se envía como query param al conectar:

```
ws://localhost:8000/ws/sala?token=eyJhbGci...
ws://localhost:8000/ws/privado/{otro_usuario_id}?token=eyJhbGci...
ws://localhost:8000/ws/grupo/{grupo_id}?token=eyJhbGci...
```

### Mensaje de chat (enviado y recibido)

```json
{
  "id": "abc123",
  "tipo": "sala | privado | grupo",
  "subtipo": "texto | imagen",
  "remitente_id": "id_usuario",
  "nombre_remitente": "Juan",
  "contenido": "Hola! | /uploads/chat/uuid.jpg",
  "destinatario_id": "id (solo privado)",
  "grupo_id": "id (solo grupo)",
  "leido": false,
  "created_at": "2024-01-15T10:30:00Z"
}
```

### Evento especial — mensajes leídos

Cuando el receptor abre un chat privado y marca los mensajes como leídos, se emite a todos los clientes de esa sala:

```json
{
  "tipo": "mensajes_leidos",
  "lector_id": "id_receptor",
  "remitente_id": "id_remitente"
}
```

---

## Servicios internos

### `redis_service.py`

| Función | Descripción |
|---|---|
| `cachear_sesion(token)` | `SETEX sesion:{token} 86400 "1"` |
| `verificar_sesion(token)` | `GET sesion:{token}` → `"1"` si activa |
| `invalidar_sesion_cache(token)` | `DEL sesion:{token}` |
| `usuario_conectado(usuario_id)` | `INCR presencia:{usuario_id}` |
| `usuario_desconectado(usuario_id)` | `DECR`, elimina clave si llega a 0 |
| `esta_conectado(usuario_id)` | `GET presencia:{usuario_id}` > 0 |

### `rabbit_service.py`

- Exchange `chat_mensajes` tipo **FANOUT** (durable) — entrega a todas las colas conectadas.
- Cola exclusiva/anónima por instancia del backend (se destruye al desconectar).
- `publicar_mensaje(sala, datos)` — serializa a JSON y publica en el exchange.
- `iniciar_consumer()` — se suscribe al exchange; cada mensaje recibido llama a `manager.broadcast()`.

### `twilio_service.py`

El SDK de Twilio es síncrono. Para no bloquear el event loop de asyncio se ejecuta en un thread pool:
```python
await asyncio.to_thread(
    client.verify.v2.services(sid).verifications.create,
    to=telefono, channel="sms"
)
```

> En cuentas trial de Twilio, los SMS solo se pueden enviar a números verificados manualmente en la consola.

### `log_service.py`

Registra eventos de auditoría en la colección `logs`:
```python
await registrar_log(
    action="USER_LOGIN",
    status="success",
    ip="192.168.1.1",
    user_id="abc123",
    details={"telefono": "3001234567"}
)
```

### Limpieza automática de estados (background task)

En `main.py`, al arrancar la app se lanza:
```python
asyncio.create_task(_limpiar_estados_expirados())
```
Cada 60 segundos: busca estados con `expira_at <= now` → elimina archivo del disco → borra documento de MongoDB.

---

## Variables de entorno

Crear `.env` en la raíz de `backend_chat/`:

```env
# MongoDB
MONGODB_URI=mongodb://localhost:27017
DATABASE_NAME=jht_chat

# JWT
SECRET_KEY=genera_una_clave_muy_larga_y_aleatoria
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440

# CORS (separar por coma si hay múltiples orígenes)
ALLOWED_ORIGINS=http://localhost:5173,http://localhost:3000

# Redis
REDIS_URL=redis://localhost:6379

# RabbitMQ
RABBITMQ_URL=amqp://guest:guest@localhost/

# Twilio Verify (opcional — solo necesario para OTP por SMS)
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_VERIFY_SID=VAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Generar un `SECRET_KEY` seguro:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

---

## Instalación y puesta en marcha

### Requisitos previos

- Python 3.10+
- MongoDB 7.0 (`localhost:27017`)
- Redis (`localhost:6379`)
- RabbitMQ (`localhost:5672`)

### Instalar y arrancar

```bash
# 1. Entrar al directorio del backend
cd project_chat/backend_chat

# 2. Crear y activar entorno virtual
python3 -m venv venv
source venv/bin/activate        # Linux / macOS / WSL
# venv\Scripts\activate         # Windows

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Configurar variables de entorno
cp .env.example .env
nano .env   # editar con los valores correctos

# 5. Arrancar el servidor en modo desarrollo
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Al arrancar correctamente verás:
```
Conectado a MongoDB: jht_chat
Conectado a Redis
Conectado a RabbitMQ y consumer activo
INFO: Application startup complete.
INFO: Uvicorn running on http://0.0.0.0:8000
```

### Arrancar la infraestructura (WSL / Ubuntu)

```bash
# MongoDB
sudo systemctl start mongod
# o manualmente:
~/mongodb/bin/mongod --dbpath ~/mongodb/data --logpath ~/mongodb/log/mongod.log --fork

# Redis
redis-server --daemonize yes
redis-cli ping   # debe responder: PONG

# RabbitMQ
sudo rabbitmq-server -detached
sudo rabbitmqctl status   # verificar que está corriendo
```

### Documentación interactiva

Con el servidor corriendo:
- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

---

## Despliegue en producción

### Con PM2

```bash
cd ~/project_chat/backend_chat
source venv/bin/activate

pm2 start venv/bin/uvicorn \
  --name backend-chat \
  --interpreter venv/bin/python3 \
  --cwd /ruta/absoluta/backend_chat \
  -- main:app --host 127.0.0.1 --port 8000

pm2 save
pm2 startup   # ejecutar el comando que genere
```

### Actualizar en producción

```bash
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
pm2 restart backend-chat
pm2 logs backend-chat --lines 20
```

### Configuración Nginx (proxy inverso)

```nginx
server {
    listen 80;
    server_name api.tudominio.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        # Soporte WebSocket
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        # Mantener conexiones WS abiertas
        proxy_read_timeout 86400;
        proxy_send_timeout 86400;
    }
}
```

### RabbitMQ Management UI en producción

El puerto 15672 no se expone públicamente. Acceder via túnel SSH desde tu PC local:

```bash
# Abrir el túnel (dejar corriendo)
ssh -L 15672:localhost:15672 usuario@IP_DEL_SERVIDOR -N

# Acceder en el navegador
# http://localhost:15672   usuario: guest / contraseña: guest
```

---

## Flujos principales

### Registro sin OTP (default)
```
POST /auth/registro { nombre, telefono, codigo: "" }
  → Verifica que el teléfono no exista
  → Inserta documento en usuarios
  → Genera JWT
  → Guarda sesión en MongoDB + Redis (TTL 24h)
  → Retorna { access_token, usuario_id, nombre }
```

### Registro con OTP (toggle activado en la UI)
```
POST /auth/enviar-otp { telefono }
  → Verifica que el teléfono NO esté registrado
  → Llama Twilio Verify → envía SMS al usuario

POST /auth/registro { nombre, telefono, codigo: "123456" }
  → Verifica OTP con Twilio
  → Si es válido → inserta usuario → genera JWT
```

### Enviar imagen en chat
```
POST /mensajes/imagen (multipart)
  → Pillow: convierte a JPEG, redimensiona a máx 1200px, calidad 75%
  → Guarda en uploads/chat/{uuid}.jpg
  → Inserta en MongoDB: { subtipo: "imagen", contenido: "/uploads/chat/uuid.jpg" }
  → Publica en RabbitMQ
  → Consumer hace broadcast a todos los clientes de la sala
```

### Estado (story)
```
POST /estados (multipart)
  → Pillow: convierte a JPEG, redimensiona a máx 1080px, calidad 80%
  → Guarda en uploads/estados/{uuid}.jpg
  → Inserta en MongoDB con expira_at = now + 5 min

GET /estados
  → Retorna estados propios + de contactos del usuario
  → Filtra documentos con expira_at <= now (ya expirados)

(Cada 60s — background task)
  → Busca { expira_at: { $lte: now } }
  → Elimina archivo del disco
  → Elimina documento de MongoDB
```

### Errores comunes

| Error | Causa | Solución |
|---|---|---|
| `Connection refused :8000` | Backend no está corriendo | `uvicorn main:app --port 8000 --reload` |
| `ModuleNotFoundError` al arrancar | venv no activado | `source venv/bin/activate` |
| `MongoDB connection refused` | mongod no está corriendo | `sudo systemctl start mongod` |
| `Redis connection refused` | Redis no está corriendo | `redis-server --daemonize yes` |
| `RabbitMQ connection refused` | RabbitMQ no está corriendo | `sudo rabbitmq-server -detached` |
| `CORS error` en el browser | Origen no permitido | Agregar origen a `ALLOWED_ORIGINS` en `.env` |
| `502 Bad Gateway` en nginx | Backend no escucha | `pm2 status` → `pm2 restart backend-chat` |
| WebSocket no conecta en prod | Falta `Upgrade`/`Connection` en nginx | Verificar headers proxy en configuración nginx |
