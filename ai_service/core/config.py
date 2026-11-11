from pydantic_settings import BaseSettings
from dotenv import load_dotenv
from typing import List, Any, Union
from pydantic import field_validator
from pydantic import Field, model_validator

load_dotenv()

class Settings(BaseSettings):
    # Database
    mongo_url: str = "mongodb+srv://CamAI_DB:Xinhzai1102%40%40@cluster0.1xazymq.mongodb.net/"
    # mongo_url: str = "mongodb://localhost:27017"
    mongo_db: str = "CamAI_Honda"
    
    # CORS
    cors_origins: str = "http://localhost:3000"
    
    # Environment
    app_env: str = "development"
    app_debug: bool = True
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    
    # Logging
    log_level: str = "INFO"

    #RCS
    ics_host: str = "192.168.50.39"
    logic_path: str = "http://192.168.1.2"

    #Camera 
    group_id: Any = []
    num_process: int = 4
    max_retry_attempts: int = 3
    weight_path: str = "yolov8n.pt"
    target_fps: float = 5.0

    # Cluster mode starts with no cameras and never reads the legacy Mongo groups.
    cluster_enabled: bool = False
    worker_id: str = ""
    worker_token: str = ""
    master_url: str = "http://127.0.0.1:8001"
    cluster_heartbeat_interval: float = Field(default=3.0, gt=0)
    cluster_http_timeout: float = Field(default=2.0, gt=0)
    cluster_lease_margin: float = Field(default=1.0, ge=0)
    cluster_max_frame_age: float = Field(default=3.0, gt=0)
    cluster_report_interval: float = Field(default=1.0, gt=0)
    cluster_report_batch_size: int = Field(default=32, ge=1)
    cluster_inference_batch_size: int = Field(default=16, ge=1)
    cluster_inference_timeout: float = Field(default=10.0, gt=0)
    cluster_model_start_timeout: float = Field(default=120.0, gt=0)
    cluster_capture_open_timeout_ms: int = Field(default=4000, ge=1)
    cluster_capture_read_timeout_ms: int = Field(default=4000, ge=1)
    cluster_camera_stop_timeout: float = Field(default=6.0, gt=0)
    cluster_start_concurrency: int = Field(default=8, ge=1)
    cluster_source_retry_delay: float = Field(default=2.0, gt=0)
    cluster_process_restart_delay: float = Field(default=3.0, gt=0)

    @model_validator(mode="after")
    def validate_cluster(self):
        if self.cluster_enabled:
            if self.app_debug:
                raise ValueError("Cluster AI requires APP_DEBUG=false")
            if not self.worker_id.strip() or not self.worker_token.strip():
                raise ValueError("Cluster mode requires WORKER_ID and WORKER_TOKEN")
            if self.num_process < 1 or self.target_fps <= 0:
                raise ValueError("NUM_PROCESS and TARGET_FPS must be positive")
            if not self.master_url.startswith(("http://", "https://")):
                raise ValueError("MASTER_URL must be an HTTP(S) base URL")
        return self

    @field_validator("group_id", mode="before")
    @classmethod
    def parse_group_id(cls, v: Any):
        # Nếu là chuỗi (từ .env gửi qua) như "1" hoặc "1,2,3"
        if isinstance(v, str):
            try:
                return [int(x.strip()) for x in v.split(",") if x.strip()]
            except ValueError:
                return []
        # Nếu đã là list (giá trị mặc định hoặc truyền trực tiếp)
        if isinstance(v, list):
            return v
        # Nếu là số nguyên đơn lẻ (trường hợp hiếm gặp khi nạp từ nguồn khác)
        if isinstance(v, int):
            return [v]
        return []

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"

settings = Settings()
