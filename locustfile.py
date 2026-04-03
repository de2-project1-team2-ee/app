"""
부하 테스트 — Locust
동시 사용자 N명이 쿠폰을 동시에 수령하는 시나리오

실행 방법:
  pip install locust
  locust -f locustfile.py --host http://localhost:8000

  # 헤드리스 모드 (빠른 테스트)
  locust -f locustfile.py --host http://localhost:8000 \
         --headless -u 500 -r 100 --run-time 30s
  # -u 500  : 동시 사용자 500명
  # -r 100  : 초당 100명씩 증가
  # --run-time 30s : 30초간 실행
"""

import uuid
from locust import HttpUser, task, between


class CouponUser(HttpUser):
    wait_time = between(0.1, 0.5)  # 요청 간격: 0.1~0.5초

    def on_start(self):
        """각 가상 사용자마다 고유 ID 생성"""
        self.user_id = f"load-{uuid.uuid4().hex[:8]}"

    @task
    def claim_coupon(self):
        """쿠폰 수령 요청"""
        self.client.post(
            "/coupon",
            json={"user_id": self.user_id},
            headers={"X-User-Id": self.user_id},
        )

    @task(3)
    def check_status(self):
        """상태 조회 (수령보다 3배 빈번하게)"""
        self.client.get("/status")
