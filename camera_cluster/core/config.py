"""Configuration for the independent camera allocation service."""
from pathlib import Path
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parents[1] / ".env",
                                     case_sensitive=False, extra="ignore")
    app_host: str = "0.0.0.0"
    app_port: int = Field(default=8002, ge=1, le=65535)
    app_debug: bool = False
    log_level: str = "INFO"
    cluster_camera_config_path: str = "config/cameras.json"
    cluster_boot_state_path: str = "runtime/cluster_boot.json"
    cluster_max_cameras: int = Field(default=1000, ge=1)
    cluster_max_rois_per_camera: int = Field(default=256, ge=1)
    cluster_history_limit: int = Field(default=1000, ge=0)
    cluster_worker_tokens: dict[str, str] = Field(default_factory=dict)
    cluster_heartbeat_interval: float = Field(default=3.0, gt=0)
    cluster_lease_seconds: float = Field(default=15.0, gt=0)
    cluster_tick_seconds: float = Field(default=1.0, gt=0)
    cluster_recovery_delay: float = Field(default=10.0, ge=0)
    cluster_rebalance_batch: int = Field(default=10, ge=1)

    @model_validator(mode="after")
    def validate_runtime(self):
        if self.app_debug:
            raise ValueError("Camera coordinator requires one process and APP_DEBUG=false")
        if not self.cluster_worker_tokens or not all(k.strip() and v.strip() for k,v in self.cluster_worker_tokens.items()):
            raise ValueError("CLUSTER_WORKER_TOKENS must map unique worker IDs to nonempty tokens")
        if self.cluster_lease_seconds <= self.cluster_heartbeat_interval * 2:
            raise ValueError("Lease must exceed two heartbeat intervals")
        if not self.cluster_camera_config_path.strip() or not self.cluster_boot_state_path.strip():
            raise ValueError("Camera config and boot state paths are required")
        return self
