"""Camera management only: no inference, detection ingest, POS or robot API."""
import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from api.cluster import router
from core.config import Settings
from services.cluster_runtime import ClusterError, get_runtime, start_runtime


@asynccontextmanager
async def lifespan(app):
    settings = Settings()
    if int(os.environ.get("WEB_CONCURRENCY", "1")) != 1:
        raise RuntimeError("Camera coordinator supports exactly one application worker")
    logging.basicConfig(level=settings.log_level.upper())
    runtime = await start_runtime(settings)
    app.state.runtime = runtime
    try:
        yield
    finally:
        await runtime.stop()


app = FastAPI(title="Camera Cluster Coordinator", version="1.0.0", lifespan=lifespan)
app.include_router(router)


@app.get("/")
async def root():
    return {"service": "camera_cluster", "role": "camera allocation"}


@app.get("/health")
async def health():
    try:
        get_runtime().require_ready()
    except ClusterError as exc:
        raise HTTPException(exc.status, exc.message) from exc
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    settings = Settings()
    uvicorn.run("main:app", host=settings.app_host, port=settings.app_port, reload=False, workers=1)
