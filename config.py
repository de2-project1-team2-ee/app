"""
환경변수 설정
.env 파일 또는 K8s ConfigMap/Secret에서 주입
"""

import os
from dataclasses import dataclass


@dataclass
class Config:
    # DB 접속 정보 (K8s 환경변수와 동일한 키 사용)
    DB_HOST: str = os.getenv("DB_HOST", "localhost")
    DB_PORT: int = int(os.getenv("DB_PORT", "5432"))
    DB_NAME: str = os.getenv("DB_NAME", "sampledb")
    DB_USER: str = os.getenv("DB_USER", "appuser")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "changeme123!")

    # 쿠폰 설정
    COUPON_TOTAL: int = int(os.getenv("COUPON_TOTAL", "300"))
    COUPON_OPEN_TIME: str = os.getenv("COUPON_OPEN_TIME", "")  # HH:MM (빈값 = 수동 오픈)

    # DB 커넥션 풀
    DB_POOL_MIN: int = int(os.getenv("DB_POOL_MIN", "10"))
    DB_POOL_MAX: int = int(os.getenv("DB_POOL_MAX", "50"))

    @property
    def database_url(self) -> str:
        return f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"


config = Config()