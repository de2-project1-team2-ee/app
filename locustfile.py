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
import logging
from locust import HttpUser, task, between, events

logger = logging.getLogger("locust.db")


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """테스트 시작 시 DB 연결 상태 확인"""
    logger.info("=== 부하 테스트 시작 — DB 연결 상태 확인 ===")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """테스트 종료 시 DB 연결 상태 최종 확인"""
    logger.info("=== 부하 테스트 종료 ===")


class CouponUser(HttpUser):
    wait_time = between(0.1, 0.5)  # 요청 간격: 0.1~0.5초

    def on_start(self):
        """각 가상 사용자마다 고유 ID 생성 + DB 연결 확인"""
        self.user_id = f"load-{uuid.uuid4().hex[:8]}"
        self._check_db_health()

    def _check_db_health(self):
        """DB 헬스체크 (/healthz) 호출 및 로그 출력"""
        with self.client.get("/healthz", name="/healthz (DB check)", catch_response=True) as resp:
            if resp.status_code == 200:
                data = resp.json()
                logger.info(f"[{self.user_id}] DB 연결 정상: {data}")
                resp.success()
            else:
                logger.error(f"[{self.user_id}] DB 연결 실패: status={resp.status_code}, body={resp.text}")
                resp.failure(f"DB unhealthy: {resp.status_code}")

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

    @task(1)
    def check_db_connection(self):
        """주기적으로 DB 연결 상태 확인"""
        self._check_db_health()
