"""
Manager de conexiones WebSocket para JHT Chat.

Concurrencia controlada con asyncio:

- asyncio.Lock (lock_conexiones):
    Protege el diccionario de conexiones activas (salas) contra condiciones de carrera.
    Se adquiere cada vez que se agrega o elimina una conexión del registro.

- asyncio.Lock (lock_presencia):
    Protege el contador de usuarios conectados (presencia en línea).
    Separado de lock_conexiones para no bloquear broadcasts mientras se
    actualiza la presencia.

- asyncio.Semaphore (sem_broadcast):
    Limita el número de broadcasts simultáneos al máximo definido en MAX_BROADCASTS.
    Evita saturar el event loop con demasiadas corrutinas de envío al mismo tiempo.
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

        # Presencia: user_id → número de conexiones WS activas
        # Un usuario puede estar en múltiples salas simultáneamente
        self.usuarios_conectados: Dict[str, int] = {}

        # Lock para modificaciones al mapa de salas (broadcast seguro)
        self.lock_conexiones: asyncio.Lock = asyncio.Lock()

        # Lock separado para el contador de presencia
        # Evita que actualizar presencia bloquee operaciones de sala
        self.lock_presencia: asyncio.Lock = asyncio.Lock()

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
        Incrementa el contador de conexiones del usuario.
        Protegido con lock_presencia para evitar condiciones de carrera
        cuando el mismo usuario abre múltiples pestañas o salas.
        """
        async with self.lock_presencia:
            self.usuarios_conectados[usuario_id] = (
                self.usuarios_conectados.get(usuario_id, 0) + 1
            )

    async def usuario_desconectado(self, usuario_id: str) -> None:
        """
        Decrementa el contador. Cuando llega a 0, el usuario queda offline.
        Protegido con lock_presencia.
        """
        async with self.lock_presencia:
            count = self.usuarios_conectados.get(usuario_id, 0)
            if count <= 1:
                self.usuarios_conectados.pop(usuario_id, None)
            else:
                self.usuarios_conectados[usuario_id] = count - 1

    def esta_conectado(self, usuario_id: str) -> bool:
        """Retorna True si el usuario tiene al menos una conexión WS activa."""
        return self.usuarios_conectados.get(usuario_id, 0) > 0

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
