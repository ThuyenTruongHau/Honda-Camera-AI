from pydantic_settings import BaseSettings
from dotenv import load_dotenv
from pydantic import Field, model_validator

load_dotenv()

class Settings(BaseSettings):
    # CORS
    cors_origins: str = "http://localhost:3000"
    
    # Environment
    app_env: str = "development"
    app_debug: bool = True
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    
    # Logging
    log_level: str = "INFO"

    # RCS
    ics_host: str = "192.168.50.39"

    # Service
    time_recognition: int = 5

    cluster_enabled: bool = False
    cluster_robot_enabled: bool = False
    cluster_camera_config_path: str = "config/cameras.json"
    cluster_boot_state_path: str = "runtime/cluster_boot.json"
    cluster_max_cameras: int = Field(default=1000, ge=1)
    cluster_max_rois_per_camera: int = Field(default=256, ge=1)
    cluster_history_limit: int = Field(default=1000, ge=0)
    cluster_sse_queue_size: int = Field(default=128, ge=1)
    cluster_sse_max_clients: int = Field(default=32, ge=1)
    cluster_worker_tokens: dict[str, str] = {}
    cluster_heartbeat_interval: float = Field(default=3.0, gt=0)
    cluster_lease_seconds: float = Field(default=15.0, gt=0)
    cluster_tick_seconds: float = Field(default=1.0, gt=0)
    cluster_recovery_delay: float = Field(default=10.0, ge=0)
    cluster_max_frame_age: float = Field(default=3.0, gt=0)
    cluster_clock_skew: float = Field(default=1.0, ge=0)
    cluster_rebalance_batch: int = Field(default=10, ge=1)

    @model_validator(mode="after")
    def validate_cluster(self):
        if self.cluster_enabled:
            if not self.cluster_worker_tokens or not all(self.cluster_worker_tokens.values()):
                raise ValueError("CLUSTER_WORKER_TOKENS must map worker IDs to nonempty tokens")
            if self.cluster_lease_seconds <= self.cluster_heartbeat_interval * 2:
                raise ValueError("Lease must exceed two heartbeat intervals")
            if self.app_debug:
                raise ValueError("Cluster master requires APP_DEBUG=false (one process, no reload)")
            if not self.cluster_camera_config_path.strip() or not self.cluster_boot_state_path.strip():
                raise ValueError("Cluster camera config and boot state paths are required")
        return self

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"

settings = Settings()
