"""
Manager de conexiones WebSocket para JHT Chat.

Concurrencia controlada con asyncio:

- asyncio.Lock (lock_conexiones):
    Protege el diccionario de conexiones activas (salas) contra condiciones de carrera.
    Se adquiere cada vez que se agrega o elimina una conexión del registro.

- asyncio.Semaphore (sem_broadcast):
    Limita el número de broadcasts simultáneos al máximo definido en MAX_BROADCASTS.
    Evita saturar el event loop con demasiadas corrutinas de envío al mismo tiempo.

- Redis (presencia):
    El tracking de usuarios conectados usa Redis en lugar de un dict in-memory.
    Las operaciones INCR/DECR son atómicas, lo que elimina la necesidad de
    lock_presencia. La presencia persiste ante reinicios del servidor y es
    compatible con despliegues multi-instancia.
"""
import asyncio
from typing import Dict, Set
from fastapi import WebSocket


MAX_BROADCASTS = 10


class ConnectionManager:
    """
    Gestiona conexiones WebSocket activas por sala y rastrea presencia de usuarios.

    Salas:
        - "sala_general": chat público
        - "privado_{userA}_{userB}": chat privado (IDs ordenados)
        - "grupo_{grupo_id}": chat de grupo
    """

    def __init__(self):
        self.salas: Dict[str, Set[WebSocket]] = {}

        # Lock para modificaciones al mapa de salas (broadcast seguro)
        self.lock_conexiones: asyncio.Lock = asyncio.Lock()

        # Semáforo para limitar broadcasts concurrentes
        self.sem_broadcast: asyncio.Semaphore = asyncio.Semaphore(MAX_BROADCASTS)

    async def conectar(self, websocket: WebSocket, sala: str) -> None:
        """Acepta la conexión y la registra en la sala. Thread-safe con lock_conexiones."""
        await websocket.accept()
        async with self.lock_conexiones:
            if sala not in self.salas:
                self.salas[sala] = set()
            self.salas[sala].add(websocket)

    async def desconectar(self, websocket: WebSocket, sala: str) -> None:
        """Elimina la conexión de la sala. Thread-safe con lock_conexiones."""
        async with self.lock_conexiones:
            if sala in self.salas:
                self.salas[sala].discard(websocket)
                if not self.salas[sala]:
                    del self.salas[sala]

    async def usuario_conectado(self, usuario_id: str) -> None:
        """
        Registra al usuario como online en Redis.
        Incrementa su contador de conexiones activas (soporta múltiples pestañas).
        La operación INCR de Redis es atómica, sin necesidad de lock adicional.
        """
        from app.services.redis_service import marcar_online
        await marcar_online(usuario_id)

    async def usuario_desconectado(self, usuario_id: str) -> None:
        """
        Decrementa el contador en Redis. Cuando llega a 0, el usuario queda offline.
        """
        from app.services.redis_service import marcar_offline
        await marcar_offline(usuario_id)

    async def esta_conectado(self, usuario_id: str) -> bool:
        """Retorna True si el usuario tiene al menos una conexión WS activa (consulta Redis)."""
        from app.services.redis_service import esta_online
        return await esta_online(usuario_id)

    async def broadcast(self, sala: str, mensaje: dict) -> None:
        """
        Envía mensaje a todos en la sala.
        sem_broadcast limita la concurrencia máxima de broadcasts simultáneos.
        """
        async with self.sem_broadcast:
            async with self.lock_conexiones:
                conexiones = set(self.salas.get(sala, set()))
            for conexion in conexiones:
                try:
                    await conexion.send_json(mensaje)
                except Exception:
                    pass

    def clave_privada(self, user_a: str, user_b: str) -> str:
        """Clave de sala privada simétrica (orden de IDs no importa)."""
        ids_ordenados = sorted([user_a, user_b])
        return f"privado_{ids_ordenados[0]}_{ids_ordenados[1]}"

    def clave_grupo(self, grupo_id: str) -> str:
        return f"grupo_{grupo_id}"


manager = ConnectionManager()
