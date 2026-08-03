"""FastAPI 앱 진입점."""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlmodel import Session, select

from app.db import create_db_and_tables, get_session
from app.models import RobotStatus, Telemetry
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


# ═══════════════════════════════════════════════════════════
# REST — 조회
# ═══════════════════════════════════════════════════════════
@app.get("/robots")
def list_robots(
    status: RobotStatus | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """현재 로봇 목록.

    ⚠️ DB 가 아니라 **메모리(fleet)** 에서 읽습니다.
       DB 의 robots 는 시작 시 한 번 넣은 뒤 갱신하지 않아서 위치가 낡았습니다.
       "지금 어디 있나"의 진실은 메모리에 있어요(state.py 참고).
       → 그래서 이 엔드포인트는 DB 세션이 필요 없습니다.

    limit 기본 100: 1,000대를 통째로 주면 응답이 커지고, 애초에 이 API 는
    실시간 화면용이 아닙니다(그건 WebSocket). 목록·검색용입니다.
    """
    robots = list(fleet.values())
    if status is not None:
        robots = [r for r in robots if r.status == status]
    return {
        "total": len(robots),
        "limit": limit,
        "offset": offset,
        "items": robots[offset:offset + limit],
    }


@app.get("/robots/{robot_id}")
def get_robot(robot_id: int):
    robot = fleet.get(robot_id)
    if robot is None:
        raise HTTPException(status_code=404, detail=f"robot {robot_id} not found")
    return robot


@app.get("/robots/{robot_id}/telemetry")
def get_robot_telemetry(
    robot_id: int,
    since: datetime | None = None,
    limit: int = Query(500, ge=1, le=5000),
    session: Session = Depends(get_session),
):
    """과거 궤적 — 이건 **DB** 에서 읽습니다.

    실시간은 메모리, 과거는 DB. 이 경계가 이 프로젝트의 핵심 설계입니다.

    ⚠️ 최근 5초는 아직 버퍼에 있어서 DB 에 없습니다(배치 주기).
       "방금 것이 왜 없냐"는 질문이 나올 지점이고, 그게 배치 저장의
       설계상 비용입니다. 필요하면 buffer 도 같이 훑도록 바꿀 수 있지만
       그러면 이 API 가 메모리 상태에 의존하게 됩니다.

    복합 인덱스 (robot_id, recorded_at) 가 이 쿼리를 위해 있습니다.
    """
    if robot_id not in fleet:
        raise HTTPException(status_code=404, detail=f"robot {robot_id} not found")

    query = select(Telemetry).where(Telemetry.robot_id == robot_id)
    if since is not None:
        query = query.where(Telemetry.recorded_at >= since)
    # 최신순으로 limit 개를 뽑고 되돌립니다.
    # 오래된 순으로 뽑으면 "가장 최근 500개"가 아니라 "가장 오래된 500개"가 됩니다.
    rows = session.exec(
        query.order_by(Telemetry.recorded_at.desc()).limit(limit)
    ).all()
    return {"robot_id": robot_id, "count": len(rows), "items": list(reversed(rows))}

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
