"""이벤트 루프가 얼마나 막히나 — to_thread 가 실제로 값을 하는지 잰다.

════════════════════════════════════════════════════════════
bench_write.py 는 **처리량**을 쟀습니다 ("60만 행에 몇 초").
이 파일은 **지연**을 잽니다 ("그동안 남이 얼마나 기다렸나").

둘은 다른 축입니다. C(executemany)는 처리량 1등이지만, 5초치 5만 행을
한 번에 넣으면 1,095ms 가 걸립니다(측정값). 그 1초 동안 이벤트 루프가
멈추면 시뮬레이터도 WebSocket 도 전부 정지합니다.

  → "서버가 얼마나 자주, 얼마나 오래 얼어붙나"를 재야 합니다.
════════════════════════════════════════════════════════════

재는 방법 — 심장박동(heartbeat)

  10ms 마다 깨어나기로 한 코루틴을 하나 띄워놓고, 실제로 언제 깨어났는지를 봅니다.
  이벤트 루프가 안 막혔으면 10ms 쯤에 깨어납니다.
  200ms 늦게 깨어났다면 그동안 루프가 200ms 막혀 있었다는 뜻입니다.

      지연(lag) = 실제 깨어난 시각 - 깨어나기로 한 시각

  이건 실무에서 이벤트 루프 건강을 재는 표준 수법입니다.
  (Node.js 의 event loop lag 와 같은 개념)

실행
    cd backend
    uv run python -m scripts.bench_blocking

┌─ 측정 결과 (로봇 1,000대, 12초 관측, 5초마다 5만 행 flush) ──
│  ※ 두 방식을 **각각 별도 프로세스**에서 돌렸습니다. 한 프로세스에서
│    연달아 돌렸더니 앞 측정이 남긴 디스크/캐시 상태가 뒤를 오염시켰습니다.
│
│   방식              쓴 행 수    지연중앙값    p99      최대     >100ms   tick밀림 최대
│   직접 호출         100,000     1.08ms    17.7ms  3,999.8ms     2회    3,871ms
│   asyncio.to_thread 100,000     1.07ms    25.5ms     65.0ms     0회      밀림 없음
│
├─ 읽는 법 ──────────────────────────────────────────────────
│
│  ✅ 최악 지연 3,999.8ms → 65.0ms (**61배**). 이게 사용자가 느끼는 값입니다.
│     직접 호출은 5초마다 서버가 통째로 4초 멈춥니다. 그동안 WebSocket 도,
│     /health 도, 시뮬레이터 tick 도 전부 정지합니다(tick 이 3.9초 밀림).
│
│  ⚠️ 그런데 **p99 는 오히려 나빠졌습니다** (17.7ms → 25.5ms).
│     to_thread 가 공짜가 아니라는 증거입니다. SQLite 의 C 코드는 GIL 을
│     놓지만 SQL 컴파일·파라미터 바인딩은 파이썬이라 GIL 을 잡습니다.
│     그 조각들이 메인 스레드에 잔 지터로 퍼집니다.
│
│     → 즉 to_thread 는 "느림을 없앤 것"이 아니라
│       **드문 대형 정지를 잦은 소형 지터로 바꾼 거래**입니다.
│       100ms tick 주기와 60fps 화면에는 이 거래가 압도적으로 유리합니다.
│       (25ms 지터는 안 보이고, 4초 정지는 장애로 보입니다)
│
│  · 처리량은 둘 다 같습니다(100,000행). 바뀐 건 지연 분포뿐입니다.
│    bench_write.py 의 표만 봤다면 이 차이를 영영 못 봤을 겁니다.
└────────────────────────────────────────────────────────────
"""

import asyncio
from statistics import median

from sqlalchemy import insert, text
from sqlmodel import Session, SQLModel, create_engine

from app.config import RANDOM_SEED, ROBOT_COUNT, TICK_MS
from app.models import Robot, Telemetry, utcnow
from app.simulator import tick
from app.state import fleet, init_fleet, rng

HEARTBEAT_MS = 10        # 심장박동 주기
DURATION_SEC = 12        # 측정 시간 (5초 배치가 2번 돌 만큼)
BATCH_SEC = 5
ROWS_PER_FLUSH = 50_000  # 5초치 = 50 tick × 1,000대


def make_rows() -> list[dict]:
    now = utcnow()
    return [
        {
            "robot_id": r.id, "x": r.x, "y": r.y, "z": r.z,
            "battery": r.battery, "speed": r.speed, "heading": r.heading,
            "status": r.status, "recorded_at": now,
        }
        for r in fleet.values()
    ]


def fresh_engine(name: str):
    from pathlib import Path
    path = Path(f"./data/blk_{name}.db")
    for suf in ("", "-wal", "-shm"):
        Path(f"{path}{suf}").unlink(missing_ok=True)
    eng = create_engine(f"sqlite:///{path}",
                        connect_args={"check_same_thread": False})
    with eng.connect() as c:
        c.exec_driver_sql("PRAGMA journal_mode=WAL")
    SQLModel.metadata.create_all(eng)

    # ⚠️ 여기서 실제로 걸려 넘어졌던 함정 (기록해둘 것)
    #
    #   app/db.py 의 @event.listens_for(Engine, "connect") 는 **Engine 클래스 전역**에
    #   걸립니다. 특정 엔진이 아니라요. 그래서 app.db 를 import 하기만 하면
    #   (여기선 app.simulator → app.persistence → app.db 로 간접 import)
    #   이 스크립트가 따로 만든 엔진에도 PRAGMA foreign_keys=ON 이 적용됩니다.
    #
    #   robots 테이블이 비어 있으면 telemetry INSERT 가 전부 FK 위반으로 죽고,
    #   그 예외가 asyncio 태스크 안에서 조용히 삼켜져서
    #   "측정은 돌았는데 DB 가 24KB" 인 상태가 됩니다. 숫자는 나오는데 의미가 없죠.
    #
    #   → 교훈: 벤치 결과를 믿기 전에 **DB 파일 크기부터 보세요.**
    #     기대한 데이터가 실제로 들어갔는지 확인 안 하면 노이즈를 해석하게 됩니다.
    seed_robots(eng)
    return eng


def seed_robots(engine) -> None:
    """telemetry.robot_id 가 FK 라서 로봇 행이 먼저 있어야 합니다."""
    with Session(engine) as s:
        s.execute(insert(Robot), [
            {"id": r.id, "name": r.name, "type": r.type, "status": r.status,
             "x": r.x, "y": r.y, "z": r.z, "battery": r.battery,
             "created_at": utcnow()}
            for r in fleet.values()
        ])
        s.commit()


def flush(engine, rows: list[dict]) -> None:
    with Session(engine) as s:
        s.execute(insert(Telemetry), rows)
        s.commit()


async def heartbeat(lags: list[float], stop: asyncio.Event) -> None:
    """10ms 마다 깨어나기로 하고, 실제로 얼마나 늦게 깨어났는지 기록."""
    loop = asyncio.get_running_loop()
    period = HEARTBEAT_MS / 1000
    while not stop.is_set():
        target = loop.time() + period
        await asyncio.sleep(period)
        lags.append((loop.time() - target) * 1000)   # ms


async def simulator(ticks: list[float], stop: asyncio.Event) -> None:
    """실제 시뮬레이터와 같은 구조. tick 주기가 밀리는지도 같이 본다."""
    loop = asyncio.get_running_loop()
    start, n = loop.time(), 0
    while not stop.is_set():
        tick()
        n += 1
        target = start + n * (TICK_MS / 1000)
        ticks.append((loop.time() - target) * 1000)
        await asyncio.sleep(max(0, target - loop.time()))


async def persister(engine, rows: list[dict], stop: asyncio.Event,
                    use_thread: bool) -> None:
    while not stop.is_set():
        await asyncio.sleep(BATCH_SEC)
        if stop.is_set():
            break
        if use_thread:
            await asyncio.to_thread(flush, engine, rows)
        else:
            flush(engine, rows)          # ← 이벤트 루프를 통째로 점유


async def run(use_thread: bool) -> dict:
    rng.seed(RANDOM_SEED)
    fleet.clear()
    init_fleet()
    engine = fresh_engine("thread" if use_thread else "block")

    # flush 에 넣을 5만 행을 미리 만들어둠 (행 생성 비용은 관심사가 아니므로)
    rows = []
    while len(rows) < ROWS_PER_FLUSH:
        tick()
        rows.extend(make_rows())
    rows = rows[:ROWS_PER_FLUSH]

    lags: list[float] = []
    tick_lags: list[float] = []
    stop = asyncio.Event()

    tasks = [
        asyncio.create_task(heartbeat(lags, stop)),
        asyncio.create_task(simulator(tick_lags, stop)),
        asyncio.create_task(persister(engine, rows, stop, use_thread)),
    ]
    await asyncio.sleep(DURATION_SEC)
    stop.set()
    for t in tasks:
        t.cancel()
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # ⚠️ 태스크가 조용히 죽지 않았는지 반드시 확인.
    #    asyncio 태스크의 예외는 아무도 안 물어보면 삼켜집니다.
    for r in results:
        if isinstance(r, Exception) and not isinstance(r, asyncio.CancelledError):
            raise RuntimeError(f"측정 중 태스크가 죽었습니다: {r!r}")

    # 그리고 기대한 데이터가 실제로 들어갔는지도 확인.
    with Session(engine) as s:
        written = s.execute(text("SELECT COUNT(*) FROM telemetry")).scalar_one()
    if written == 0:
        raise RuntimeError("telemetry 가 0행입니다 — 측정이 아무것도 안 썼습니다")
    engine.dispose()

    ordered = sorted(lags)
    return {
        "written": written,
        "lag_median": median(lags),
        "lag_p99": ordered[int(len(ordered) * 0.99)],
        "lag_max": max(lags),
        "over_100ms": sum(1 for x in lags if x > 100),
        "tick_max": max(tick_lags),
        "beats": len(lags),
    }


async def main() -> None:
    print(f"조건  로봇 {ROBOT_COUNT}대, 심장박동 {HEARTBEAT_MS}ms, "
          f"{DURATION_SEC}초 관측, {BATCH_SEC}초마다 {ROWS_PER_FLUSH:,}행 flush\n")

    results = {}
    for label, use_thread in (("직접 호출 (블로킹)", False),
                              ("asyncio.to_thread", True)):
        results[label] = await run(use_thread)

    print(f"{'방식':<22}{'박동 수':>9}{'지연 중앙값':>12}{'p99':>10}"
          f"{'최대':>10}{'100ms초과':>10}{'tick밀림 최대':>14}")
    print("─" * 88)
    for label, r in results.items():
        print(f"{label:<22}{r['beats']:>9,}{r['lag_median']:>11.2f}ms"
              f"{r['lag_p99']:>9.1f}ms{r['lag_max']:>9.1f}ms"
              f"{r['over_100ms']:>10}{r['tick_max']:>13.1f}ms")

    print("\n읽는 법")
    print("  지연 중앙값 : 평소 이벤트 루프가 얼마나 여유로운가")
    print("  최대        : 최악의 순간 서버가 얼마나 오래 얼어붙었나  ← 사용자가 느끼는 것")
    print("  100ms 초과  : 60fps 는커녕 10fps 도 안 나오는 구간이 몇 번 있었나")
    print("  tick밀림    : 시뮬레이터가 100ms 주기를 얼마나 놓쳤나")


if __name__ == "__main__":
    asyncio.run(main())
