"""FastAPI 앱 진입점."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from app.db import create_db_and_tables
from app.persistence import flush_now, run_persister, stats, sync_robots
from app.simulator import run_simulator
from app.state import fleet, init_fleet
from app.ws import manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── 켜질 때 ──────────────────────────────
    create_db_and_tables()
    init_fleet()
    sync_robots()       # ← telemetry FK 가 참조할 robots 행을 먼저 확보
    tasks = [
        asyncio.create_task(run_simulator()),
        asyncio.create_task(run_persister()),   # 5초마다 배치 저장
    ]

    yield                       # ← 서버가 운영되는 구간

    # ── 꺼질 때 ──────────────────────────────
    for task in tasks:
        task.cancel()
    for task in tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass
    # 루프를 세운 뒤에 남은 버퍼를 마저 저장합니다.
    # 순서가 중요합니다 — 시뮬레이터를 먼저 안 세우면 저장하는 동안에도
    # 버퍼가 계속 쌓여서 "마지막"이 영원히 안 옵니다.
    await flush_now()

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


@app.get("/debug/persistence")
def get_persistence_stats():
    """배치 저장이 잘 따라가고 있는지 보는 창.

    rows_dropped 가 0 이 아니면 DB 쓰기가 생성 속도를 못 따라가는 중입니다.
    max_flush_ms 가 배치 주기(5,000ms)에 가까워지면 한계 신호.
    """
    return {"persistence": stats, "websocket": manager.stats,
            "clients": len(manager.active)}


# ═══════════════════════════════════════════════════════════
# WebSocket — 실시간
# ═══════════════════════════════════════════════════════════
@app.websocket("/ws/telemetry")
async def ws_telemetry(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # 💭 받을 것도 없는데 왜 receive_text() 로 기다리나?
            #    서버→클라 단방향인데도 이 루프가 필요합니다.
            #    (1) 이 함수가 끝나면 FastAPI 가 연결을 닫아버립니다.
            #    (2) 클라이언트가 끊었다는 걸 알아채는 방법이 이것뿐입니다
            #        — receive 가 WebSocketDisconnect 를 던져줍니다.
            #    Week 03 에서 여기로 뷰포트 정보가 올라옵니다.
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        # 정상적인 끊김이 아닌 경우에도 명단에서는 반드시 빼야 합니다.
        # 안 그러면 죽은 소켓이 브로드캐스트마다 예외를 던집니다.
        manager.disconnect(websocket)
        raise


# ── 참고: lifespan 패턴 설명 (구현은 위에 있음) ─────────────
# TODO(2주차) — 완료
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
