from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from shared.logger import setup_logger
from core.config import settings
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = setup_logger("camera_ai_service", "INFO", "ai")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    # Startup
    logger.info("Starting CameraAI Service...")
    if settings.cluster_enabled:
        from services.cluster_runtime import ClusterAIService
        ai_service = ClusterAIService(settings)
    else:
        from services.camera_orchestrator_service import CameraOrchestratorService
        ai_service = CameraOrchestratorService(settings.group_id, settings.num_process, settings.max_retry_attempts, settings.weight_path, settings.target_fps)
    app.state.ai_service = ai_service

    try:
        logger.info("Initializing Camera Detector...")
        if not settings.cluster_enabled:
            from core.database import connect_to_mongo
            await connect_to_mongo(settings.mongo_url, settings.mongo_db)
            logger.info("Database connected")
        await ai_service.start()
        logger.info("AI service is running on")
        yield
    except Exception:
        logger.error("Error initializing Camera Detector")
        raise
    finally:
        logger.info("Shutting down Camera Detector...")
        try:
            await ai_service.stop()
        finally:
            if not settings.cluster_enabled:
                from core.database import close_mongo_connection
                await close_mongo_connection()
        logger.info("AI_service stopped")

# Create FastAPI app
app = FastAPI(
    title="Camera AI Service",
    description="AI-powered camera service",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"message": "Camera AI Service API", "version": "1.0.0"}

@app.get("/health")
async def health_check():
    if settings.cluster_enabled:
        from fastapi import HTTPException
        service = getattr(app.state, "ai_service", None)
        if not service or not service.ready():
            detail = service.health.get("error_type", "AI model or capture runtime is not ready") if service and service.manager else "AI runtime is starting"
            raise HTTPException(503, detail)
        return {"status": "healthy", "registered": service.registered,
                "cameras": len(service.assignments), "stopping": len(service.stopping)}
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_debug
    )
