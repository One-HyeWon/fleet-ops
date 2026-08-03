"""배치 저장 — 메모리의 fleet 를 주기적으로 DB 에 몰아 쓴다.

════════════════════════════════════════════════════════════
왜 이 파일이 이렇게 생겼나 — 전부 측정에서 나왔습니다
(근거: scripts/bench_write.py 헤더의 표)

  ① executemany 를 쓴다 (ORM add 아님)
     1,000대 × 600 tick 기준  ORM add 53.6s → executemany 9.9s (5.4배)
     이 5.4배는 fsync 절감이 아닙니다. 두 방식의 커밋 주기를 똑같이 맞춰놓고
     쟀으니까요. 순수하게 **ORM 우회**(객체 생성·검증·변경추적)의 이득입니다.

  ② 트랜잭션을 무작정 키우지 않는다
     "전부 모았다가 commit 1번"은 A(매 tick commit)보다 **느렸습니다**(0.8배).
     60만 객체가 세션에 살아남아 peak RSS 1.3GB. fsync 를 아끼려다 메모리로 갚음.

  ③ flush 를 워커 스레드로 넘긴다  ← 이 파일의 핵심
     5초치(5만 행)를 한 번에 넣으면 **1,095ms** 걸립니다(max 7.8s).
     그냥 await 없이 부르면 그 1.1초 동안 이벤트 루프가 통째로 멈춥니다.
     시뮬레이터도, WebSocket 브로드캐스트도, /health 도 전부 정지.
     → 5초마다 1.1초씩 얼어붙는 대시보드가 됩니다(시간의 20%).

     ⚠️ 처리량(9.9s)과 지연(1.1s)은 다른 축입니다.
        벤치 표만 보면 이 문제가 안 보입니다.
════════════════════════════════════════════════════════════

이 파일이 하는 일은 셋뿐입니다.

    record()        매 tick, 지금 상태를 버퍼에 쌓는다      (시뮬레이터가 호출)
    _flush(rows)    버퍼를 DB 에 한 번에 넣는다             (워커 스레드에서 실행)
    run_persister() 5초마다 버퍼를 비워 _flush 로 넘긴다     (백그라운드 태스크)
"""

import asyncio
import logging
import time

from sqlalchemy import insert, select
from sqlmodel import Session

from app.config import BATCH_INTERVAL_SEC, TELEMETRY_SAMPLE_EVERY_TICKS
from app.db import engine
from app.models import Robot, Telemetry, utcnow
from app.state import fleet

log = logging.getLogger(__name__)

# 버퍼가 이 이상 쌓이면 오래된 것부터 버립니다.
# 샘플링(1초마다) 기준 5초치가 5,000행이므로 30만 행 ≈ 5분치입니다.
# 그보다 밀렸다면 DB 가 회복 불가능하게 느린 상황이고, 메모리를 지키는 쪽이 낫습니다.
# ⚠️ "버린다"는 선택입니다. 결제 데이터였다면 절대 이러면 안 됩니다.
#    텔레메트리는 최신값이 더 중요하고, 어차피 실시간 화면은 메모리에서 나옵니다.
MAX_BUFFER_ROWS = 300_000

_buffer: list[dict] = []

# 관측용 카운터 — 이슈에 쓸 숫자이자 운영 중 문제를 알아채는 신호
stats = {
    "flushes": 0,
    "rows_written": 0,
    "rows_dropped": 0,
    "last_flush_ms": 0.0,
    "max_flush_ms": 0.0,
}


def sync_robots() -> None:
    """메모리의 fleet 에 있는 로봇 중 DB 에 없는 것을 넣는다 (앱 시작 시 1회).

    ── 왜 필요한가 (실제로 여기서 터졌습니다) ──────────────────
    init_fleet() 은 **메모리만** 채웁니다. DB 의 robots 테이블은 비어 있어요.
    그런데 telemetry.robot_id 는 robots.id 를 참조하는 FK 입니다.
    → 로봇을 먼저 안 넣으면 배치 저장이 통째로 FK 위반으로 죽습니다.

    그리고 그 실패가 **조용합니다**. 서버는 /health 에 200 을 주고,
    시뮬레이터도 잘 돌고, WebSocket 도 잘 나갑니다. DB 만 안 쌓여요.

    ⚠️ 이 함수는 "없는 것만" 넣습니다. 재시작할 때마다 지우고 다시 넣으면
       기존 telemetry 가 참조하던 로봇이 사라져서 FK 가 깨집니다.
       (SQLite 는 FK 를 꺼두면 조용히 통과시킵니다 — 그래서 더 위험)
    """
    with Session(engine) as s:
        existing = set(s.execute(select(Robot.id)).scalars())
        missing = [
            {
                "id": r.id, "name": r.name, "type": r.type, "status": r.status,
                "x": r.x, "y": r.y, "z": r.z, "battery": r.battery,
                "last_seen_at": r.last_seen_at, "created_at": utcnow(),
            }
            for r in fleet.values()
            if r.id not in existing
        ]
        if missing:
            s.execute(insert(Robot), missing)
            s.commit()
            log.info("robots %d행 시드", len(missing))


_tick_count = 0


def record() -> None:
    """매 tick 호출되지만, 실제로 쌓는 건 TELEMETRY_SAMPLE_EVERY_TICKS 마다 한 번.

    ⚠️ 여기가 **샘플링**입니다. 배치(버퍼링)와 다른 층의 결정이에요.
       버퍼링은 "모아서 한 번에 쓴다"(데이터는 그대로),
       샘플링은 "애초에 덜 만든다"(데이터를 버림).
       매 tick 쌓으면 초당 1만 행이고, 그러면 어떤 쓰기 전략도 결국 밀립니다
       (config.py 의 실측 기록 참고 — flush 44초, 143만 행 폐기).

    왜 Telemetry 객체가 아니라 dict 인가:
      executemany 가 dict 리스트를 받습니다. 그리고 사전 측정에서
      Telemetry(**row) 는 21.7µs/개, dict 는 0.16µs/개 였습니다(135배).
    """
    global _tick_count
    _tick_count += 1
    if _tick_count % TELEMETRY_SAMPLE_EVERY_TICKS != 0:
        return

    now = utcnow()
    _buffer.extend(
        {
            "robot_id": r.id, "x": r.x, "y": r.y, "z": r.z,
            "battery": r.battery, "speed": r.speed, "heading": r.heading,
            "status": r.status, "recorded_at": now,
        }
        for r in fleet.values()
    )

    if len(_buffer) > MAX_BUFFER_ROWS:
        overflow = len(_buffer) - MAX_BUFFER_ROWS
        del _buffer[:overflow]
        stats["rows_dropped"] += overflow
        log.warning(
            "버퍼 초과로 %d행 폐기 (누적 %d행) — DB 쓰기가 생성 속도를 못 따라감",
            overflow, stats["rows_dropped"],
        )


def _take_buffer() -> list[dict]:
    """버퍼를 통째로 넘겨받고 새 리스트로 갈아끼운다(swap).

    ⚠️ 왜 복사가 아니라 swap 인가
       flush 는 1초 넘게 걸리고, 그동안 시뮬레이터는 계속 record() 를 부릅니다.
       같은 리스트를 순회하면서 뒤에서 append 하면 무슨 일이 벌어질지 보장이 없어요.
       참조를 떼어내고 전역은 빈 리스트로 바꾸면, 이후 append 는 새 리스트로 갑니다.

       global 로 재대입하는 이유가 이것입니다. _buffer.clear() 를 쓰면
       flush 로 넘긴 그 리스트를 비우는 셈이라 데이터가 사라집니다.
    """
    global _buffer
    rows, _buffer = _buffer, []
    return rows


def _flush(rows: list[dict]) -> None:
    """워커 스레드에서 실행되는 동기 함수. 여기가 1초씩 걸리는 구간.

    db.py 에서 check_same_thread=False 를 켜둔 것이 이걸 위한 것이었습니다.
    (SQLite 는 기본적으로 "커넥션을 만든 스레드에서만 써라"고 막습니다)
    """
    with Session(engine) as s:
        s.execute(insert(Telemetry), rows)
        s.commit()


async def run_persister() -> None:
    """BATCH_INTERVAL_SEC 마다 버퍼를 비워 DB 로 넘기는 백그라운드 루프."""
    while True:
        await asyncio.sleep(BATCH_INTERVAL_SEC)

        rows = _take_buffer()
        if not rows:
            continue

        t0 = time.perf_counter()

        # ★ 여기가 이 파일의 존재 이유
        #   await asyncio.to_thread(...) 는 "이 동기 함수를 워커 스레드에서 돌리고,
        #   끝날 때까지 나는 양보한다"는 뜻입니다. 그동안 이벤트 루프는
        #   시뮬레이터 tick 과 WebSocket 브로드캐스트를 계속 돌립니다.
        #
        #   측정값(scripts/bench_blocking.py): 최악 지연 4,000ms → 65ms
        #
        #   ⚠️ 완전히 공짜는 아닙니다. SQLite 의 C 코드는 GIL 을 놓지만
        #      SQL 컴파일·파라미터 바인딩은 파이썬이라 GIL 을 잡습니다.
        #      실제로 p99 는 17.7ms → 25.5ms 로 **나빠졌습니다**.
        #      드문 대형 정지를 잦은 소형 지터로 바꾼 거래입니다.
        try:
            await asyncio.to_thread(_flush, rows)
        except Exception:
            # ⚠️ 여기서 예외를 안 잡으면 이 태스크가 죽고, 그 예외는
            #    아무도 await 하지 않으므로 **조용히 삼켜집니다.**
            #    서버는 /health 에 200 을 주고 시뮬레이터도 잘 도는데
            #    DB 만 안 쌓이는 상태가 됩니다. 실제로 이걸로 한 번 당했습니다
            #    (robots 테이블 미시드 → FK 위반 → flush 전멸, 무증상).
            #
            #    그래서 (1) 로그를 남기고 (2) 루프는 계속 돕니다.
            #    한 번 실패했다고 저장을 영영 포기할 이유는 없으니까요.
            #    이 버퍼분은 버립니다 — 되돌려 넣으면 같은 이유로 또 실패하면서
            #    무한히 쌓입니다.
            stats["rows_dropped"] += len(rows)
            log.exception("flush 실패 — %d행 폐기 (누적 %d행)",
                          len(rows), stats["rows_dropped"])
            continue

        elapsed_ms = (time.perf_counter() - t0) * 1000

        stats["flushes"] += 1
        stats["rows_written"] += len(rows)
        stats["last_flush_ms"] = elapsed_ms
        stats["max_flush_ms"] = max(stats["max_flush_ms"], elapsed_ms)

        # flush 가 주기보다 오래 걸리면 버퍼가 계속 자랍니다.
        # 이 경고가 뜨기 시작하면 BATCH_INTERVAL_SEC 를 늘리거나
        # 샘플링(데이터를 버리는 쪽)으로 넘어갈 때입니다.
        if elapsed_ms > BATCH_INTERVAL_SEC * 1000:
            log.warning(
                "flush 가 배치 주기보다 오래 걸림: %.0fms > %ds",
                elapsed_ms, BATCH_INTERVAL_SEC,
            )

        log.info("flush %d행 / %.0fms", len(rows), elapsed_ms)


async def flush_now() -> None:
    """서버 종료 시 남은 버퍼를 마저 저장 (lifespan 에서 호출).

    이걸 안 하면 Ctrl+C 마다 최대 5초치가 사라집니다.
    "서버가 죽으면 그 5초는 날아가는데 괜찮은가"는 예상 질문인데,
    **정상 종료**에서까지 날릴 이유는 없습니다. 갑작스러운 종료(SIGKILL,
    전원 차단)에서 5초를 잃는 것은 설계상 받아들인 비용이고, 그 둘은 다릅니다.
    """
    rows = _take_buffer()
    if rows:
        await asyncio.to_thread(_flush, rows)
        stats["flushes"] += 1
        stats["rows_written"] += len(rows)
        log.info("종료 전 flush %d행", len(rows))
