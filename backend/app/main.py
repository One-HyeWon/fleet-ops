"""FastAPI 앱 진입점."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import create_db_and_tables
from app.simulator import run_simulator
from app.state import fleet, init_fleet


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── 켜질 때 ──────────────────────────────
    create_db_and_tables()
    init_fleet()
    task = asyncio.create_task(run_simulator())

    yield                       # ← 서버가 운영되는 구간

    # ── 꺼질 때 ──────────────────────────────
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

app = FastAPI(title="FleetOps API", lifespan=lifespan)


@app.get("/health")
def health():
    """서버가 살아 있는지 확인하는 용도.

    Docker나 배포 환경이 "이 컨테이너 정상인가?"를 물어볼 때 쓰는 관례적인 엔드포인트입니다.
    """
    return {"status": "ok"}


@app.get("/debug/fleet")
def get_fleet():
    """현재 풀의 로봇 상태를 반환합니다."""
    return {
        "count": len(fleet),
        "sample": [fleet[i] for i in (1, 2, 3)],
    }

# TODO(2주차)
#   [ ] lifespan 등록 — 앱이 뜰 때 테이블 생성 + 시뮬레이터 루프 시작
#   [ ] GET  /robots
#   [ ] GET  /robots/{id}/telemetry
#   [ ] WS   /ws/telemetry
#
# ── lifespan 패턴 ──────────────────────────────────────────
#
#   from contextlib import asynccontextmanager
#
#   @asynccontextmanager
#   async def lifespan(app: FastAPI):
#       # ↓ yield 위: 앱이 켜질 때 한 번
#       create_db_and_tables()
#       init_fleet()
#       task = asyncio.create_task(run_simulator())
#
#       yield          # ← 여기서 서버가 운영됨 (요청을 받는 구간)
#
#       # ↓ yield 아래: 앱이 꺼질 때 한 번
#       task.cancel()
#
#   app = FastAPI(title="FleetOps API", lifespan=lifespan)
#
#   · yield 하나를 기준으로 위=시작, 아래=종료. 파이썬의 컨텍스트 매니저 문법입니다.
#     (with 문이 들어갈 때/나올 때 뭔가 하는 것과 같은 구조)
#
#   · asyncio.create_task() 는 "이 코루틴을 백그라운드에서 돌려줘"라는 뜻입니다.
#     await 로 부르면 시뮬레이터가 끝날 때까지 여기서 멈춰서 서버가 안 뜹니다.
#     run_simulator() 는 무한 루프라 영원히 안 끝나요.
#
#   · task.cancel() 을 안 하면 Ctrl+C 때 "Task was destroyed but it is pending!"
#     경고가 뜹니다. 시작한 건 정리하는 게 예의.
