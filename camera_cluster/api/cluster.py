from fastapi import APIRouter, HTTPException
from schemas.cluster import RegisterRequest, HeartbeatRequest
from services.cluster_runtime import get_runtime, ClusterError

router = APIRouter(prefix="/cluster", tags=["Camera cluster"])


async def invoke(action, data):
    try:
        return await getattr(get_runtime(), action)(data)
    except ClusterError as exc:
        raise HTTPException(exc.status, exc.message) from exc


@router.post("/register")
async def register(data: RegisterRequest):
    return await invoke("register", data)


@router.post("/heartbeat")
async def heartbeat(data: HeartbeatRequest):
    return await invoke("heartbeat", data)


@router.get("/state")
async def state():
    try:
        return await get_runtime().state()
    except ClusterError as exc:
        raise HTTPException(exc.status, exc.message) from exc
