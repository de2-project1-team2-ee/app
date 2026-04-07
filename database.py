"""
DB 연결 풀 관리 + 테이블 초기화
앱 시작 시 테이블 생성 + 쿠폰 데이터 세팅
"""

import asyncpg
from config import config

pool: asyncpg.Pool | None = None


async def init_db() -> None:
    """앱 시작 시 호출: 커넥션 풀 생성 + 테이블 초기화"""
    global pool
    pool = await asyncpg.create_pool(
        dsn=config.database_url,
        min_size=config.DB_POOL_MIN,
        max_size=config.DB_POOL_MAX,
    )
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS coupon_event (
                id          SERIAL PRIMARY KEY,
                total       INT NOT NULL DEFAULT 300,
                remaining   INT NOT NULL DEFAULT 300,
                is_open     BOOLEAN NOT NULL DEFAULT FALSE,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS coupon (
                id          SERIAL PRIMARY KEY,
                code        VARCHAR(20) NOT NULL UNIQUE,
                user_id     VARCHAR(64) NOT NULL UNIQUE,
                claimed_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)
        # 이벤트 행이 없으면 초기 데이터 삽입
        row = await conn.fetchrow("SELECT id FROM coupon_event LIMIT 1")
        if row is None:
            await conn.execute(
                "INSERT INTO coupon_event (total, remaining, is_open) VALUES ($1, $1, FALSE)",
                config.COUPON_TOTAL,
            )
            pass


async def close_db() -> None:
    """앱 종료 시 호출: 커넥션 풀 정리"""
    global pool
    if pool:
        await pool.close()


def get_pool() -> asyncpg.Pool:
    """커넥션 풀 반환. 초기화 전 호출 시 에러"""
    if pool is None:
        raise RuntimeError("DB 커넥션 풀이 초기화되지 않았습니다")
    return pool