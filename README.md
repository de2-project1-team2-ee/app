# 🔥 핫딜 쿠폰 서비스
cicd test
선착순 할인 쿠폰 발급 서비스입니다.
K8s 멀티 파드 환경에서 동시성 제어를 통해 **초과 발급 없이 정확하게** 쿠폰을 발급합니다.

## 서비스 시나리오

1. 관리자가 쿠폰 이벤트를 오픈 (시간 설정 또는 수동)
2. 다수 사용자가 동시에 접속하여 쿠폰 수령 버튼 클릭
3. 300장이 모두 소진되면 이후 요청은 "매진" 응답
4. 동시 500명이 몰려도 500 에러 없이 정상 처리

## 기술 스택

| 구분 | 기술 |
|---|---|
| 백엔드 | Python 3.12 + FastAPI |
| DB | PostgreSQL 16 (asyncpg 비동기 드라이버) |
| 동시성 제어 | PostgreSQL Advisory Lock |
| 컨테이너 | Docker → ECR |
| 오케스트레이션 | Amazon EKS (K8s 1.34) |
| 부하 테스트 | Locust |

## 프로젝트 구조

```
app/
├── main.py              # FastAPI 앱 (API 엔드포인트)
├── database.py          # DB 커넥션 풀 + 테이블 초기화
├── config.py            # 환경변수 설정
├── templates/
│   └── index.html       # 쿠폰 수령 페이지
├── static/
│   └── style.css
├── docker-compose.yaml  # 로컬 PostgreSQL 실행용
├── Dockerfile
├── requirements.txt
├── .env                 # 환경변수 
├── locustfile.py        # 부하 테스트 스크립트
└── README.md
```

## API 엔드포인트

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/` | 쿠폰 수령 페이지 |
| POST | `/coupon` | 쿠폰 수령 |
| GET | `/status` | 잔여 쿠폰 수 조회 |
| POST | `/admin/open` | 이벤트 오픈 (시연용) |
| POST | `/admin/reset` | 쿠폰 리셋 (시연 반복용) |
| GET | `/healthz` | K8s 헬스체크 |

## 에러 응답 체계

모든 응답은 통일된 JSON 구조를 사용합니다.

**성공 시:**
```json
{
  "success": true,
  "data": { "coupon_code": "HD-A1B2C3D4", "message": "쿠폰이 발급되었습니다!", "remaining": 299 }
}
```

**실패 시:**
```json
{
  "success": false,
  "error": { "code": "SOLD_OUT", "message": "쿠폰이 모두 소진되었습니다" }
}
```

| HTTP 코드 | 에러 코드 | 상황 |
|---|---|---|
| 400 | MISSING_USER_ID | 사용자 ID 누락 |
| 403 | NOT_OPEN | 이벤트 오픈 전 |
| 409 | ALREADY_CLAIMED | 중복 수령 시도 |
| 410 | SOLD_OUT | 쿠폰 매진 |
| 500 | INTERNAL_ERROR | 서버 내부 오류 |

## 동시성 제어 방식

PostgreSQL **원자적 UPDATE + UNIQUE 제약**을 사용합니다.

```sql
UPDATE coupon_event SET remaining = remaining - 1
WHERE remaining > 0 AND is_open = TRUE
RETURNING remaining
```

- `UPDATE ... WHERE remaining > 0`이 원자적으로 실행되어 초과 차감 불가
- 중복 수령은 `coupon.user_id UNIQUE` 제약으로 DB 레벨에서 차단
- 중복 시 차감을 `remaining + 1`로 롤백
- 락을 잡지 않아 커넥션 대기 없이 고속 처리
- K8s 파드가 여러 개여도 같은 DB를 바라보므로 정합성 보장

## 로컬 실행

```bash
# 1. PostgreSQL 실행
docker compose up -d

# 2. 의존성 설치
pip install -r requirements.txt

# 3. 앱 실행
uvicorn main:app --reload --port 8000

# 4. 브라우저에서 http://localhost:8000 접속
```

```bash
# 종료
docker compose down

# 데이터까지 삭제
docker compose down -v
```

## 부하 테스트 (Locust)

```bash
# 설치
pip install locust

# Web UI 모드 (http://localhost:8089)
locust -f locustfile.py --host http://localhost:8000

# 헤드리스 모드 (CI용)
locust -f locustfile.py --host http://localhost:8000 \
       --headless -u 500 -r 100 --run-time 30s
```

**테스트 시나리오:**
1. `/admin/open` 호출하여 이벤트 오픈
2. Locust로 동시 500명 부하 발생
3. `/status`에서 정확히 300장만 발급되었는지 확인
4. 500 에러가 0건인지 확인 ← **핵심 검증 포인트**

## 환경변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| DB_HOST | localhost | PostgreSQL 호스트 |
| DB_PORT | 5432 | PostgreSQL 포트 |
| DB_NAME | sampledb | 데이터베이스명 |
| DB_USER | appuser | DB 사용자 |
| DB_PASSWORD | changeme123! | DB 비밀번호 |
| COUPON_TOTAL | 300 | 쿠폰 총 수량 |
| COUPON_OPEN_TIME | (빈값) | 오픈 시간 HH:MM (빈값 = 수동 오픈) |
| DB_POOL_MIN | 10 | DB 커넥션 풀 최소 |
| DB_POOL_MAX | 50 | DB 커넥션 풀 최대 |

## K8s 배포

기존 프로젝트 인프라(EKS + ArgoCD)를 그대로 사용합니다.
deployment.yaml의 이미지와 포트를 FastAPI 앱에 맞게 수정하면 됩니다.# CI/CD test
