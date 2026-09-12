"""Herramientas del agente: una base de datos de pedidos simulada.

El diseño es deliberado: `buscar_pedidos` pide un `cliente_id` numérico, pero el usuario
pregunta por nombre. Eso obliga al agente a encadenar dos llamadas (resolver el nombre,
después consultar los pedidos) en vez de resolverlo en un solo paso.

Los docstrings son lo único que el modelo lee para decidir qué herramienta usar. Si el
agente elige mal, el problema casi siempre está acá y no en el grafo.
"""

from typing import Any

from langchain_core.tools import tool

# --- "Base de datos" en memoria -------------------------------------------

_CLIENTES: dict[int, str] = {
    101: "Ana Gutierrez",
    102: "Bruno Salas",
    103: "Carla Ponce",
}

_PEDIDOS: dict[int, list[dict[str, Any]]] = {
    101: [
        {"pedido_id": 5001, "fecha": "2024-01-12", "monto": 4200, "estado": "entregado"},
        {"pedido_id": 5014, "fecha": "2024-02-03", "monto": 1800, "estado": "entregado"},
    ],
    102: [
        {"pedido_id": 5002, "fecha": "2024-01-15", "monto": 7300, "estado": "entregado"},
        {"pedido_id": 5019, "fecha": "2024-02-20", "monto": 5100, "estado": "en_transito"},
        {"pedido_id": 5031, "fecha": "2024-03-08", "monto": 2100, "estado": "pendiente"},
    ],
    103: [],
}


@tool
def buscar_cliente(nombre: str) -> dict[str, Any]:
    """Busca un cliente por su nombre o apellido y devuelve su ID numérico.

    Usá esta herramienta cuando el usuario mencione a un cliente por nombre y necesites
    su ID para consultar otra información. La búsqueda no distingue mayúsculas y acepta
    coincidencias parciales (por ejemplo "Ana" encuentra a "Ana Gutierrez").

    Devuelve {"cliente_id": int, "nombre": str} si hay una única coincidencia.
    Si no encuentra a nadie devuelve {"error": "...", "clientes_disponibles": [...]}.
    Si hay varias coincidencias devuelve {"error": "...", "coincidencias": [...]} y
    tenés que pedirle al usuario que aclare a cuál se refiere.
    """
    q = nombre.strip().lower()
    hits = [(cid, n) for cid, n in _CLIENTES.items() if q in n.lower()]

    if not hits:
        return {
            "error": f"No existe ningún cliente que coincida con '{nombre}'.",
            "clientes_disponibles": list(_CLIENTES.values()),
        }
    if len(hits) > 1:
        return {
            "error": f"'{nombre}' coincide con más de un cliente. Pedile al usuario que aclare.",
            "coincidencias": [{"cliente_id": c, "nombre": n} for c, n in hits],
        }
    cid, n = hits[0]
    return {"cliente_id": cid, "nombre": n}


@tool
def buscar_pedidos(cliente_id: int) -> dict[str, Any]:
    """Devuelve todos los pedidos de un cliente a partir de su ID numérico.

    Requiere el ID numérico del cliente, NO su nombre. Si sólo tenés el nombre, usá
    primero la herramienta buscar_cliente para obtener el ID.

    Devuelve {"cliente_id": int, "cantidad": int, "total": int, "pedidos": [...]},
    donde cada pedido trae pedido_id, fecha, monto y estado.
    Si el ID no existe devuelve {"error": "..."}.
    """
    if cliente_id not in _PEDIDOS:
        return {
            "error": f"No existe el cliente con ID {cliente_id}.",
            "ids_validos": sorted(_PEDIDOS),
        }
    pedidos = _PEDIDOS[cliente_id]
    return {
        "cliente_id": cliente_id,
        "cantidad": len(pedidos),
        "total": sum(p["monto"] for p in pedidos),
        "pedidos": pedidos,
    }


@tool
def detalle_pedido(pedido_id: int) -> dict[str, Any]:
    """Devuelve el detalle completo de un pedido puntual a partir de su pedido_id.

    Usala cuando el usuario pregunte por un pedido específico y ya conozcas su ID
    (por ejemplo, después de haberlo obtenido con buscar_pedidos).

    Devuelve el pedido con sus artículos y su transportista.
    Si el pedido_id no existe devuelve {"error": "..."}.
    """
    for cid, pedidos in _PEDIDOS.items():
        for p in pedidos:
            if p["pedido_id"] == pedido_id:
                return {
                    **p,
                    "cliente_id": cid,
                    "cliente": _CLIENTES[cid],
                    "articulos": ["teclado mecánico", "hub USB-C"],
                    "transportista": "Andreani",
                }
    return {"error": f"No existe el pedido {pedido_id}."}


HERRAMIENTAS = [buscar_cliente, buscar_pedidos, detalle_pedido]
