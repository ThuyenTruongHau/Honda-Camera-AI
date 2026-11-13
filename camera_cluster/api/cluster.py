from fastapi import APIRouter, Header, HTTPException
from schemas.cluster import RegisterRequest, HeartbeatRequest
from services.cluster_runtime import get_runtime, ClusterError

router = APIRouter(prefix="/cluster", tags=["Camera cluster"])


def authenticated(worker_id, authorization):
    runtime = get_runtime()
    token = authorization[7:] if authorization and authorization.startswith("Bearer ") else ""
    runtime.authenticate(worker_id, token)
    return runtime


async def invoke(action, data, authorization):
    try:
        return await getattr(authenticated(data.worker_id, authorization), action)(data)
    except ClusterError as exc:
        raise HTTPException(exc.status, exc.message) from exc


@router.post("/register")
async def register(data: RegisterRequest, authorization: str = Header(default="")):
    return await invoke("register", data, authorization)


@router.post("/heartbeat")
async def heartbeat(data: HeartbeatRequest, authorization: str = Header(default="")):
    return await invoke("heartbeat", data, authorization)


@router.get("/state")
async def state(worker_id: str, authorization: str = Header(default="")):
    try:
        return await authenticated(worker_id, authorization).state()
    except ClusterError as exc:
        raise HTTPException(exc.status, exc.message) from exc
