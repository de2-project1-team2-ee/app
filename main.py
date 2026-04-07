"""
핫딜 쿠폰 서비스 — FastAPI
동시성 제어: PostgreSQL UPDATE ... RETURNING + UNIQUE 제약으로 초과 발급 방지
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config import config
from database import init_db, close_db, get_pool
from coupon_queue import start_queue, stop_queue, enqueue_coupon

# ── 로깅 설정 ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("hotdeal")


# ── 앱 라이프사이클 ──
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await start_queue()
    logger.info("핫딜 쿠폰 서비스 시작")
    yield
    await stop_queue()
    await close_db()
    logger.info("핫딜 쿠폰 서비스 종료")


app = FastAPI(title="HotDeal Coupon Service", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# ── 에러 응답 헬퍼 ──
def error_response(status: int, message: str, code: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"success": False, "error": {"code": code, "message": message}},
    )


def success_response(data: dict) -> JSONResponse:
    return JSONResponse(
        status_code=200,
        content={"success": True, "data": data},
    )


# ──────────────────────────────────────────────
# 1. 메인 페이지
# ──────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# ──────────────────────────────────────────────
# 2. 쿠폰 수령 (핵심 — 동시성 제어)
#
# 방식: UPDATE ... SET remaining = remaining - 1
#       WHERE remaining > 0 AND is_open = TRUE
#       RETURNING remaining
#
# - 락 없이 원자적 차감 (DB가 행 단위로 처리)
# - remaining이 0 이하면 UPDATE 영향 행 = 0 → 매진
# - 중복 수령은 coupon 테이블 UNIQUE(user_id)로 차단
# - Advisory Lock과 달리 커넥션을 오래 잡지 않음
# ──────────────────────────────────────────────
@app.post("/coupon")
async def claim_coupon(request: Request):
    # 사용자 식별
    user_id = request.headers.get("X-User-Id", "")
    if not user_id:
        try:
            body = await request.json()
            user_id = body.get("user_id", "")
        except Exception:
            pass
    if not user_id:
        return error_response(400, "사용자 ID가 필요합니다", "MISSING_USER_ID")

    # 큐에 넣고 워커가 처리할 때까지 대기
    result = await enqueue_coupon(user_id)

    if result["success"]:
        return success_response(result["data"])
    else:
        err = result["error"]
        return error_response(result["status"], err["message"], err["code"])


# ──────────────────────────────────────────────
# 3. 쿠폰 상태 조회
# ──────────────────────────────────────────────
@app.get("/status")
async def coupon_status():
    pool = get_pool()
    try:
        async with pool.acquire(timeout=3) as conn:
            event = await conn.fetchrow(
                "SELECT total, remaining, is_open FROM coupon_event LIMIT 1"
            )
            if event is None:
                return error_response(500, "이벤트가 설정되지 않았습니다", "NO_EVENT")
    except asyncio.TimeoutError:
        return error_response(503, "서버가 바쁩니다", "SERVER_BUSY")

    return success_response({
        "total": event["total"],
        "remaining": event["remaining"],
        "is_open": event["is_open"],
        "claimed": event["total"] - event["remaining"],
    })


# ──────────────────────────────────────────────
# 4. 관리자 — 쿠폰 오픈 (시연용)
# ──────────────────────────────────────────────
@app.post("/admin/open")
async def admin_open():
    pool = get_pool()
    async with pool.acquire() as conn:
        event = await conn.fetchrow("SELECT is_open FROM coupon_event LIMIT 1")
        if event and event["is_open"]:
            return error_response(409, "이미 오픈된 상태입니다", "ALREADY_OPEN")

        await conn.execute("UPDATE coupon_event SET is_open = TRUE")

    logger.info("쿠폰 이벤트 오픈!")
    return success_response({"message": "쿠폰 이벤트가 오픈되었습니다!"})


# ──────────────────────────────────────────────
# 5. 관리자 — 리셋 (시연 반복용)
# ──────────────────────────────────────────────
@app.post("/admin/reset")
async def admin_reset():
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM coupon")
            await conn.execute(
                "UPDATE coupon_event SET remaining = $1, is_open = FALSE",
                config.COUPON_TOTAL,
            )

    logger.info("쿠폰 이벤트 리셋: %d장", config.COUPON_TOTAL)
    return success_response({"message": f"쿠폰 {config.COUPON_TOTAL}장으로 리셋되었습니다"})


# ──────────────────────────────────────────────
# 6. 헬스체크 (K8s readiness/liveness probe)
# ──────────────────────────────────────────────
@app.get("/healthz")
async def healthz():
    try:
        pool = get_pool()
        async with pool.acquire(timeout=2) as conn:
            await conn.fetchval("SELECT 1")
        return {"status": "ok"}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "unhealthy"})


# ──────────────────────────────────────────────
# 글로벌 예외 핸들러 — 예상치 못한 에러도 깔끔하게
# ──────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("처리되지 않은 예외: %s", exc, exc_info=True)
    return error_response(500, "서버 내부 오류가 발생했습니다", "INTERNAL_ERROR")