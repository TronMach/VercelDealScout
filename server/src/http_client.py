# One shared httpx client per event loop.
# Created on first use instead of in a FastAPI lifespan, because serverless
# functions on Vercel may not run lifespan events.
import asyncio
import httpx

_clients: dict[int, httpx.AsyncClient] = {}

def get_client() -> httpx.AsyncClient:
    loop_id = id(asyncio.get_running_loop())
    client = _clients.get(loop_id)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0))
        _clients[loop_id] = client
    return client

async def close_clients():
    for client in _clients.values():
        await client.aclose()
    _clients.clear()
