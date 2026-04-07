"""
쿠폰 요청 내부 큐 — asyncio.Queue 기반
DB 커넥션 고갈 방지: 동시 DB 접근을 worker 수로 제한
"""

import os
import uuid
import asyncio
import logging

from database import get_pool

logger = logging.getLogger("hotdeal.queue")

# 워커 수 = 실제 동시 DB 접근 수 (풀 max보다 작게 설정)
QUEUE_WORKERS: int = int(os.getenv("QUEUE_WORKERS", "20"))
QUEUE_MAX_SIZE: int = int(os.getenv("QUEUE_MAX_SIZE", "5000"))
QUEUE_TIMEOUT: float = float(os.getenv("QUEUE_TIMEOUT", "10"))

_queue: asyncio.Queue | None = None
_workers: list[asyncio.Task] = []


async def start_queue() -> None:
    """앱 시작 시 호출: 큐 + 워커 생성"""
    global _queue
    _queue = asyncio.Queue(maxsize=QUEUE_MAX_SIZE)
    for i in range(QUEUE_WORKERS):
        task = asyncio.create_task(_worker(i), name=f"coupon-worker-{i}")
        _workers.append(task)
    pass


async def stop_queue() -> None:
    """앱 종료 시 호출: 워커 정리"""
    for w in _workers:
        w.cancel()
    await asyncio.gather(*_workers, return_exceptions=True)
    _workers.clear()
    pass


async def enqueue_coupon(user_id: str) -> dict:
    """
    쿠폰 요청을 큐에 넣고 결과를 기다린다.
    반환: {"success": True/False, "status": int, "data"|"error": ...}
    """
    if _queue is None:
        raise RuntimeError("큐가 초기화되지 않았습니다")

    future: asyncio.Future = asyncio.get_event_loop().create_future()

    try:
        _queue.put_nowait((user_id, future))
    except asyncio.QueueFull:
        return {
            "success": False,
            "status": 503,
            "error": {"code": "QUEUE_FULL", "message": "대기열이 가득 찼습니다. 잠시 후 다시 시도해주세요"},
        }

    try:
        result = await asyncio.wait_for(future, timeout=QUEUE_TIMEOUT)
        return result
    except asyncio.TimeoutError:
        return {
            "success": False,
            "status": 503,
            "error": {"code": "QUEUE_TIMEOUT", "message": "처리 시간이 초과되었습니다. 잠시 후 다시 시도해주세요"},
        }


async def _worker(worker_id: int) -> None:
    """큐에서 요청을 꺼내 DB 처리 후 결과를 future에 전달"""
    pool = get_pool()

    while True:
        user_id, future = await _queue.get()
        try:
            result = await _process_coupon(pool, user_id)
            if not future.cancelled():
                future.set_result(result)
        except Exception as exc:
            if not future.cancelled():
                future.set_result({
                    "success": False,
                    "status": 500,
                    "error": {"code": "INTERNAL_ERROR", "message": "서버 내부 오류가 발생했습니다"},
                })
        finally:
            _queue.task_done()


async def _process_coupon(pool, user_id: str) -> dict:
    """실제 DB 쿠폰 발급 로직 (워커가 호출)"""
    async with pool.acquire(timeout=5) as conn:
        # 1) 이벤트 상태 확인
        event = await conn.fetchrow(
            "SELECT is_open, remaining FROM coupon_event LIMIT 1"
        )
        if event is None:
            return _err(500, "NO_EVENT", "이벤트가 설정되지 않았습니다")
        if not event["is_open"]:
            return _err(403, "NOT_OPEN", "아직 오픈 시간이 아닙니다")
        if event["remaining"] <= 0:
            return _err(410, "SOLD_OUT", "쿠폰이 모두 소진되었습니다")

        # 2) 원자적 재고 차감
        row = await conn.fetchrow(
            """
            UPDATE coupon_event
            SET remaining = remaining - 1
            WHERE remaining > 0 AND is_open = TRUE
            RETURNING remaining
            """
        )
        if row is None:
            return _err(410, "SOLD_OUT", "쿠폰이 모두 소진되었습니다")

        remaining = row["remaining"]

        # 3) 쿠폰 발급
        coupon_code = f"HD-{uuid.uuid4().hex[:8].upper()}"
        try:
            await conn.execute(
                "INSERT INTO coupon (code, user_id) VALUES ($1, $2)",
                coupon_code, user_id,
            )
        except Exception:
            await conn.execute(
                "UPDATE coupon_event SET remaining = remaining + 1"
            )
            return _err(409, "ALREADY_CLAIMED", "이미 쿠폰을 수령했습니다")

    logger.info("쿠폰 발급: user=%s, code=%s, 잔여=%d", user_id, coupon_code, remaining)
    return {
        "success": True,
        "status": 200,
        "data": {
            "coupon_code": coupon_code,
            "message": "쿠폰이 발급되었습니다!",
            "remaining": remaining,
        },
    }


def _err(status: int, code: str, message: str) -> dict:
    return {"success": False, "status": status, "error": {"code": code, "message": message}}
