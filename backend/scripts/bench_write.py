"""쓰기 부하 측정 — "초당 5만 INSERT를 피하는 법"의 근거 자료.

📌 여기는 혜원님이 채우는 파일입니다.

════════════════════════════════════════════════════════════
이 스크립트가 답해야 하는 질문

  로봇 1,000대 × 초당 10 tick = 초당 1만 건의 텔레메트리가 생긴다.
  (설정을 5,000대로 올리면 초당 5만 건)

  이걸 DB에 어떻게 넣어야 하나? 네 가지를 재서 표로 만든다.

    A. naive     매 tick 마다 commit          ← 일부러 만드는 최악
    B. 트랜잭션   전부 모았다가 commit 1번      ← fsync 를 줄임
    C. bulk      B + executemany              ← ORM 오버헤드까지 줄임
    D. 샘플링     5초에 1번만 데이터를 만듦      ← 데이터를 버림

  A→B 가 fsync 이야기, B→C 가 ORM 이야기, C→D 가 트레이드오프 이야기입니다.
  세 개가 각각 다른 축이라 하나로 뭉뚱그리면 Deep Dive 가 안 됩니다.

  ⚠️ 단, 사전 측정에서 이 가설의 절반이 이미 깨졌습니다. 아래 참고.
════════════════════════════════════════════════════════════

┌─ 사전 측정 (primitive probe, 1,000행 1회 기준) ────────────
│  M-series 맥북 / macOS 26.6 / Python 3.12.8 / SQLite 3.47.2
│
│    tick() 1,000대                        0.92 ms
│    ORM add + commit      (1,000행)      44.6  ms
│    ORM add + flush(커밋X)(1,000행)      44.2  ms   ← 커밋만 뺌
│    executemany + commit  (1,000행)       8.8  ms
│
│    Telemetry(**row) 생성                21.7  µs/개
│    dict(row)          생성               0.16 µs/개
│
│    commit 1회  WAL+synchronous=FULL      0.101 ms
│    commit 1회  + fullfsync=ON            5.185 ms   ← 51배
│
├─ 여기서 나온 것 ───────────────────────────────────────────
│
│  (1) 44.6 - 44.2 = 0.4ms → **커밋은 전체 비용의 1%**.
│      나머지 99%가 파이썬/ORM 비용입니다.
│      → 따라서 B(트랜잭션 묶기)는 거의 이득이 없을 것으로 예상됩니다.
│        이득은 C(executemany, 5배)에서 옵니다.
│      → "매 tick commit 이 느린 건 fsync 때문"이라는 통설은
│        적어도 이 환경에서는 **거짓**입니다.
│
│  (2) 44.2ms 의 내역:  객체 생성 21.7ms + (add 변경추적 + SQL 컴파일) 22.5ms
│
│  (3) macOS 의 fsync() 는 드라이브 캐시를 안 비웁니다.
│      진짜 배리어(F_FULLFSYNC)를 켜면 51배 느려집니다.
│      즉 지금 우리 "commit 했으니 안전하다"는 **전원 차단에는 안 안전**합니다.
│      (커널 패닉에는 안전) — SQLite 가 macOS 에서 기본으로 안 켭니다.
│
│  (4) A 예상:  0.92 + 44.6 ≈ 45.5 ms/tick → 약 22 tick/s → 약 22,000 행/초
│      그리고 45.5ms 는 100ms 예산 안입니다. 1,000대면 naive 도 따라갑니다.
│      5,000대면 ~223ms 라 밀립니다.
│
│  (5) 그래서 문제 정의가 바뀝니다.
│      ❌ "초당 5만 INSERT 가 문제"   (commit 은 어차피 초당 10번뿐이었음)
│      ✅ "행당 ORM 비용 × 행 수 가 문제"
│
└─ 이 스크립트가 할 일: 위 예측이 600 tick 규모에서도 맞는지 확인 ────
│
│  스케일에서 뒤집힐 수 있는 것들 (여기를 특히 볼 것):
│    · 인덱스(ix_telemetry_robot_time)가 커지면 INSERT 비용이 오르나
│    · WAL 파일이 커지면서 checkpoint 가 끼어드는 비용
│    · 60만 객체를 세션에 쌓는 B 의 메모리
│  예측이 맞으면 근거가 되고, 틀리면 그 차이가 Deep Dive 본문이 됩니다.
└────────────────────────────────────────────────────────────

┌─ 본 측정 결과 (로봇 1,000대 × 600 tick, 3회 중앙값, WAL) ──
│
│   방식                    행 수    소요(s)   ms/tick   peak RSS   DB(MB)
│   A  매 tick commit     600,000    53.61     89.34      59 MB     83.4
│   B  전체 1 트랜잭션      600,000    65.56    109.26   1,300 MB    151.8
│   B' 50tick 마다 commit  600,000    43.04     71.74     245 MB     95.4
│   C  executemany        600,000     9.91     16.52      59 MB     95.4
│   D  5초 샘플링           12,000     0.69      1.14      59 MB      6.0
│
├─ 예측 대비 ────────────────────────────────────────────────
│
│  ✅ 맞은 것: "이득은 fsync 가 아니라 ORM 우회에서 온다"
│       A→B' 1.2배 (커밋 주기를 1/50 로 줄였는데도)
│       A→C  5.4배 (커밋 주기는 B' 와 동일. 차이는 오직 ORM 우회)
│
│  ❌ 틀린 것 1: 45.5 ms/tick 예상 → 실측 89.3 ms/tick (2배)
│       사전 측정은 **빈 DB** 기준이었습니다. tick 이 쌓이면 인덱스
│       (ix_telemetry_robot_time)가 커지면서 INSERT 가 비싸집니다.
│       20 tick 일 때 58.7 → 600 tick 일 때 89.3.
│       → 교훈: "1회 측정"을 규모로 외삽하면 틀린다.
│
│  ❌ 틀린 것 2: **B 가 A 보다 느립니다** (0.8배). 이건 예상 못 했습니다.
│       60만 개의 Telemetry 객체가 세션에 살아남아 peak RSS 1.3GB.
│       GC 압력 + flush 때 세션 전체를 훑는 비용이 fsync 절감분을 넘겼습니다.
│       → "fsync 를 아끼려고 트랜잭션을 키웠더니 메모리로 되갚았다."
│       → 순진한 "배치 = 무조건 이득"이 깨지는 지점.
│
├─ 덤으로 나온 것 ───────────────────────────────────────────
│
│  · A(83.4MB) 가 B(151.8MB) 보다 **작습니다**. A 는 커밋마다 WAL 이
│    checkpoint 되어 본 파일로 접히는데, B 는 트랜잭션이 안 끝나서
│    WAL 이 계속 자랍니다. "커밋을 미루면 디스크를 더 쓴다"
│
│  · D 는 속도가 아니라 **디스크**가 논점입니다. 95.4MB → 6.0MB (16배).
│    대신 로봇 궤적에 4.9초짜리 구멍이 생깁니다.
│
│  · 100ms 예산 대비:  A 89.3ms 는 이미 아슬아슬합니다. 여기에 WebSocket
│    브로드캐스트까지 얹으면 tick 주기가 밀립니다. C 는 16.5ms 라 여유.
│    5,000대로 선형 외삽하면 A ~447ms(밀림) / C ~83ms(아슬아슬).
│
│  ⚠️ 재현성 메모: B' 는 3회 중앙값 43.0s 였지만 단독 재측정에선 78.6s 가
│     나왔습니다(expunge_all + GC 타이밍 편차). B' 수치는 신뢰구간이 넓습니다.
│     A/C 는 재측정에서도 각각 56.4s / 13.9s 로 안정적이었습니다.
└────────────────────────────────────────────────────────────

실행
    cd backend
    uv run python -m scripts.bench_write

────────────────────────────────────────────────────────────
TODO
  [ ] ① 준비 — 깨끗한 DB 파일 + 로봇 시드
  [ ] ② make_rows()  — 한 tick 분량의 텔레메트리 만들기
  [ ] ③ A/B/C/D 네 가지 실행 함수
  [ ] ④ 결과 표 출력 (소요시간 / INSERT per sec / DB 파일 크기)
────────────────────────────────────────────────────────────
"""

import gc
import platform
import sqlite3
import sys
import time
from pathlib import Path
from statistics import median

from sqlalchemy import insert
from sqlmodel import Session, SQLModel, create_engine

from app.config import RANDOM_SEED, ROBOT_COUNT
from app.models import Robot, Telemetry, utcnow
from app.simulator import tick
from app.state import fleet, init_fleet, rng


# ─────────────────────────────────────────────────────────
# 측정 조건 — 이 숫자들이 그대로 이슈 표의 각주가 됩니다
# ─────────────────────────────────────────────────────────
#
# ⚠️ "60초 동안 돌린다"가 아니라 "600 tick 을 돈다"로 하세요.
#    시간 기준으로 하면 A(느림)와 C(빠름)가 서로 다른 양의 데이터를 만들어서
#    비교가 안 됩니다. 같은 일을 시키고 걸린 시간을 재야 합니다.
#
#    그리고 sleep 을 넣지 마세요. 우리가 재려는 건 "실시간으로 따라갈 수 있나"가
#    아니라 "쓰기 자체가 얼마나 비싼가"입니다. 최대 속도로 돌립니다.

TICKS = 600          # 600 tick = 실제 시간으로 60초 분량
REPEAT = 3           # 같은 측정을 3번 하고 중앙값을 씁니다 (한 번만 재면 튐)
SAMPLE_EVERY = 50    # D(샘플링): 50 tick = 5초에 한 번만 저장
BATCH_EVERY = 50     # B'(주기 커밋): 실제 persistence.py 가 쓸 값
# ROBOT_COUNT 는 config.py 값을 씁니다 (1,000)
# → 총 600 tick × 1,000대 = 60만 행


def reset_fleet() -> None:
    """모든 측정이 '똑같은 로봇 움직임'을 겪게 되감습니다.

    ⚠️ Week 01 메모: 시드를 고정해도 init_fleet() 을 두 번 부르면 결과가 달라집니다.
       rng 가 이어서 돌기 때문. 그래서 매번 seed 를 되감아야 tick() 비용이 동일해집니다.
       이걸 안 하면 A 와 C 가 서로 다른 로봇 상태 분포를 갖게 되고,
       (충전 중 로봇이 많으면 분기가 달라져서) tick() 비용이 미세하게 달라집니다.
    """
    rng.seed(RANDOM_SEED)
    fleet.clear()
    init_fleet()


def db_bytes(path: Path) -> int:
    """DB 크기 = .db + -wal + -shm.

    WAL 모드에선 커밋 직후 데이터가 아직 -wal 에 있습니다.
    .db 만 재면 "어? 파일이 안 커졌네?" 하게 돼요.
    """
    total = 0
    for suffix in ("", "-wal", "-shm"):
        p = Path(f"{path}{suffix}")
        if p.exists():
            total += p.stat().st_size
    return total


# ─────────────────────────────────────────────────────────
# ① 준비 — 측정마다 깨끗한 DB 로 시작
# ─────────────────────────────────────────────────────────
#
# 왜 매번 파일을 지우나:
#   앞 측정이 남긴 60만 행 위에 다음 측정을 하면 인덱스가 이미 커져 있어서
#   뒤에 잰 것이 불리해집니다. "측정 순서가 결과를 바꾸는" 실험은 무효예요.
#
#     def fresh_engine(name: str):
#         path = Path(f"./data/bench_{name}.db")
#         path.unlink(missing_ok=True)
#         Path(f"{path}-wal").unlink(missing_ok=True)   # ← WAL 파일도 같이!
#         Path(f"{path}-shm").unlink(missing_ok=True)
#         engine = create_engine(f"sqlite:///{path}", connect_args={...})
#         SQLModel.metadata.create_all(engine)
#         return engine, path
#
# ⚠️ app.db 의 engine 을 그대로 쓰지 마세요. 거기엔 이미 WAL 이 켜져 있는데,
#    WAL 유무도 나중에 재볼 변수입니다. 여기선 엔진을 직접 만들어야 통제가 됩니다.
#    (app.db 를 import 하는 순간 @event.listens_for 가 전역으로 걸리는 것에도 주의)
#
# 그리고 Telemetry 에는 robot_id FK 가 있으므로 로봇 1,000행을 먼저 넣어야 합니다.
# FK 가 켜져 있으면(우리는 켰습니다) 없는 robot_id 로 INSERT 하면 터집니다.


def fresh_engine(name: str):
    path = Path(f"./data/bench_{name}.db")
    for suffix in ("", "-wal", "-shm"):
        Path(f"{path}{suffix}").unlink(missing_ok=True)

    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
    )
    # app.db 의 전역 이벤트 리스너를 안 쓰고 여기서 직접 켭니다(통제를 위해).
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
    SQLModel.metadata.create_all(engine)
    seed_robots(engine)
    return engine, path


def seed_robots(engine) -> None:
    """Telemetry.robot_id 가 FK 라서 로봇 1,000행이 먼저 있어야 합니다."""
    with Session(engine) as s:
        s.execute(
            insert(Robot),
            [
                {
                    "id": r.id, "name": r.name, "type": r.type, "status": r.status,
                    "x": r.x, "y": r.y, "z": r.z, "battery": r.battery,
                    "created_at": utcnow(),
                }
                for r in fleet.values()
            ],
        )
        s.commit()


# ─────────────────────────────────────────────────────────
# ② make_rows() — 한 tick 분량의 텔레메트리
# ─────────────────────────────────────────────────────────
#
#     def make_rows() -> list[dict]:
#         now = utcnow()
#         return [
#             {"robot_id": r.id, "x": r.x, ..., "recorded_at": now}
#             for r in fleet.values()
#         ]
#
# 💭 왜 Telemetry 객체가 아니라 dict 인가:
#    C(executemany) 는 dict 리스트를 받습니다. B 는 객체가 필요하고요.
#    측정 함수마다 알아서 변환하게 두고, 여기선 제일 싼 형태(dict)로 만듭니다.
#    이 함수가 비싸면 A/B/C 모두에 똑같이 얹혀서 차이를 흐립니다.


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


# ─────────────────────────────────────────────────────────
# ③-A  naive — 매 tick commit
# ─────────────────────────────────────────────────────────
#
#     for _ in range(TICKS):
#         tick()
#         with Session(engine) as s:
#             for row in make_rows():
#                 s.add(Telemetry(**row))
#             s.commit()              # ← tick 마다 fsync 1번
#
# ⚠️ 이게 얼마나 걸릴지 모릅니다. 먼저 TICKS=20 으로 한 번 재보고
#    "1 tick 당 몇 ms"를 확인한 다음 600 tick 을 지를지 판단하세요.
#    600 tick × 500ms = 5분입니다. 그건 그것대로 좋은 숫자고요.
#
#    만약 너무 느려서 못 기다리겠으면 A 만 TICKS 를 줄이고
#    **INSERT/s 로 정규화**해서 비교하세요. 표에 "A 는 60 tick 만 측정"이라고
#    각주를 다는 게, 몰래 조건을 바꾸는 것보다 훨씬 좋은 글이 됩니다.
#
# 💭 예측 (사전 측정 기준): tick 당 45.5ms → 약 22 tick/s → 약 22,000 행/초
#    근거: tick 0.92ms + ORM add·commit 44.6ms. 지배적인 건 **fsync 가 아니라 ORM**.
#    이 예측이 맞는지, 그리고 tick 이 쌓이면서 인덱스 때문에 느려지는지를 봅니다.


def run_naive(engine) -> int:
    rows = 0
    for _ in range(TICKS):
        tick()
        batch = make_rows()
        with Session(engine) as s:
            for row in batch:
                s.add(Telemetry(**row))
            s.commit()          # ← tick 마다 commit
        rows += len(batch)
    return rows


# ─────────────────────────────────────────────────────────
# ③-B  트랜잭션 묶기
# ─────────────────────────────────────────────────────────
#
#     with Session(engine) as s:
#         for _ in range(TICKS):
#             tick()
#             for row in make_rows():
#                 s.add(Telemetry(**row))
#         s.commit()                  # ← 전체에서 fsync 1번
#
# ⚠️ 이건 현실적인 구현이 아닙니다. 60만 개의 파이썬 객체가 세션에 쌓여서
#    메모리가 터질 수 있어요. "fsync 를 줄이면 얼마나 빨라지나"만 보는
#    극단값 측정입니다. 실제 persistence.py 는 5초마다 commit 합니다.
#
#    메모리가 걱정되면 N tick 마다 commit 하는 버전(B')도 재보세요.
#    5초(=50 tick)마다 commit 이 우리가 실제로 쓸 값입니다.
#
# 💭 예측: **B 는 A 와 거의 같을 것입니다** (tick 당 0.4ms 차이).
#    사전 측정에서 커밋이 전체의 1% 였으니까요.
#    "배치로 바꿨는데 왜 안 빨라지지?" 가 나오면 예측이 맞은 겁니다 — 실패가 아니라
#    이번 주 Deep Dive 의 핵심 증거입니다. 이 결과를 절대 버리지 마세요.
#
#    ⚠️ 단 하나 주의: B 는 트랜잭션을 60초간 열어둡니다. SQLite 는 쓰기 락을
#       하나만 허용하므로 그동안 다른 쓰기가 전부 막힙니다. 속도표엔 안 나오지만
#       실제 서버에선 이게 더 큰 문제일 수 있어요 (→ Week 05 동시성 주제와 연결)


def run_transaction(engine) -> int:
    """B — 전체를 트랜잭션 하나로. fsync 1번."""
    rows = 0
    with Session(engine) as s:
        for _ in range(TICKS):
            tick()
            batch = make_rows()
            for row in batch:
                s.add(Telemetry(**row))
            rows += len(batch)
        s.commit()
    return rows


def run_transaction_periodic(engine) -> int:
    """B' — 50 tick(=5초)마다 commit. 실제 persistence.py 가 쓸 방식."""
    rows = 0
    with Session(engine) as s:
        for i in range(TICKS):
            tick()
            batch = make_rows()
            for row in batch:
                s.add(Telemetry(**row))
            rows += len(batch)
            if (i + 1) % BATCH_EVERY == 0:
                s.commit()
                s.expunge_all()     # 세션에 쌓인 객체를 비움(메모리)
        s.commit()
    return rows


# ─────────────────────────────────────────────────────────
# ③-C  bulk insert (executemany)
# ─────────────────────────────────────────────────────────
#
#     from sqlalchemy import insert
#
#     with Session(engine) as s:
#         for _ in range(TICKS):
#             tick()
#             s.exec(insert(Telemetry), make_rows())   # dict 리스트를 그대로
#         s.commit()
#
# 무엇이 빠지나:
#   · Telemetry(**row) 객체 생성 6만~60만 번  → 없음
#   · Pydantic 필드 검증                      → 없음
#   · 세션의 변경 추적(identity map) 등록       → 없음
#   · INSERT 문 하나에 여러 VALUES 를 묶어 보냄
#
# ⚠️ B 와 C 의 차이는 fsync 가 아닙니다(둘 다 1번). 순수하게 파이썬/ORM 비용이에요.
#    이 둘을 따로 재야 "느린 원인이 DB 인가 우리 코드인가"를 말할 수 있습니다.
#    많은 글이 이 둘을 뭉쳐서 "배치가 100배 빠르다"고만 씁니다. 우리는 쪼갭니다.
#
# 💭 예측: **여기서 처음으로 크게 빨라집니다** (44.6 → 8.8ms, 5배).
#    즉 "배치의 이득"이라고 불리는 것의 실체는 fsync 절감이 아니라 ORM 우회입니다.
#    ← 이 한 문장이 이번 주 Deep Dive 의 결론 후보입니다.
#
# 💭 확인해볼 것: C 로 넣으면 id 가 채워지지 않습니다(객체가 없으니까).
#    그게 문제가 되는 상황이 있을까요? 우리 경우엔?


def run_bulk(engine) -> int:
    """C — executemany. 50 tick 마다 commit (B' 와 커밋 주기를 맞춰 공정 비교)."""
    rows = 0
    with Session(engine) as s:
        for i in range(TICKS):
            tick()
            batch = make_rows()
            s.execute(insert(Telemetry), batch)
            rows += len(batch)
            if (i + 1) % BATCH_EVERY == 0:
                s.commit()
        s.commit()
    return rows


# ─────────────────────────────────────────────────────────
# ③-D  샘플링 — 아예 데이터를 덜 만든다
# ─────────────────────────────────────────────────────────
#
#     for i in range(TICKS):
#         tick()
#         if i % 50 == 0:              # 50 tick = 5초에 한 번만
#             rows = make_rows()
#             ...
#
# 이건 앞의 셋과 성격이 다릅니다. A/B/C 는 **같은 60만 행**을 다르게 넣는 것이고,
# D 는 **1.2만 행만 넣는 것**입니다. 그래서 "빠르다"고 말하면 안 돼요. 당연히 빠릅니다.
#
# D 에서 봐야 할 숫자는 속도가 아니라 **DB 파일 크기**와 **잃은 것**입니다.
#   · 60만 행 vs 1.2만 행 → 디스크 50배 차이
#   · 대신 로봇의 이동 궤적에 4.9초짜리 구멍이 생김
#
# 💭 우리 서비스에서 이게 허용되나?
#    · "지난 1시간 이동 경로를 그려줘"  → 5초 간격 점을 이으면 대충 맞음. OK
#    · "배터리가 언제 20% 밑으로 떨어졌나" → 최대 5초 오차. 아마 OK
#    · "충돌 직전 0.3초에 무슨 일이 있었나" → ❌ 데이터가 없음
#    마지막 항목이 관제 시스템에서 얼마나 중요한지가 판단 기준입니다.
#    (실무에선 "평소엔 샘플링, 이상 징후 땐 전량 저장" 같은 적응형을 씁니다)


def run_sampled(engine) -> int:
    """D — 50 tick(5초)에 한 번만 '데이터를 만든다'. C 와 저장 방식은 동일.

    C 와의 차이는 오직 '행 수'입니다. 그래야 C→D 가 순수하게
    "데이터를 버려서 얻는 것"만 보여줍니다.
    """
    rows = 0
    with Session(engine) as s:
        for i in range(TICKS):
            tick()
            if (i + 1) % SAMPLE_EVERY == 0:
                batch = make_rows()
                s.execute(insert(Telemetry), batch)
                rows += len(batch)
                s.commit()
    return rows


# ─────────────────────────────────────────────────────────
# ③-E  (선택) 내구성 — 우리가 안전하다고 믿은 게 사실인가
# ─────────────────────────────────────────────────────────
#
# 사전 측정에서 나온 것:
#     WAL + synchronous=FULL                  0.101 ms/commit
#     WAL + synchronous=FULL + fullfsync=ON   5.185 ms/commit   ← 51배
#
# macOS 의 fsync() 는 커널 버퍼까지만 밀고 리턴합니다. SSD 내부 캐시는 그대로예요.
# 진짜로 디스크에 박으려면 F_FULLFSYNC 가 필요한데 SQLite 는 기본으로 안 켭니다.
#
#   → 지금 우리 commit 은 **커널 패닉에는 안전, 전원 차단에는 안 안전**합니다.
#
# 💭 그런데 우리한테 이게 문제인가?
#    · 저장하는 게 텔레메트리 로그입니다. 전원 차단 시 마지막 몇 초가 날아가도
#      "5초 배치라 어차피 5초는 날아간다"와 같은 종류의 손실이에요.
#    · 즉 **우리는 fullfsync 를 안 켜는 게 맞습니다.** 다만 그건 판단이지 무지가 아니어야 합니다.
#    · 반대로 결제·주문이었다면? 51배를 내고서라도 켜야 합니다.
#
# 이 항목은 표에 안 넣어도 됩니다. 하지만 Deep Dive 에는 넣으세요 —
# "성능 수치를 낼 때 무엇을 포기하고 있었는지"를 아는 사람이 쓴 글이 됩니다.
# (Week 01 의 "SQLAlchemy Enum 이 몰래 이름을 저장하더라"와 같은 계열의 발견)


# ─────────────────────────────────────────────────────────
# ④ 결과 표
# ─────────────────────────────────────────────────────────
#
# 각 run_* 이 이런 dict 를 돌려주게 하세요:
#     {"name": "A naive", "ticks": 600, "rows": 600_000,
#      "elapsed": 312.4, "db_bytes": 84_213_760}
#
# 그리고 마지막에 표로 찍습니다. 이슈에 그대로 붙일 수 있게요:
#
#     방식          행 수      소요(s)    행/초       DB 크기
#     A naive      600,000     312.4      1,920      80.3 MB
#     B 트랜잭션    600,000       ?          ?           ?
#     C bulk       600,000       ?          ?           ?
#     D 샘플링      12,000        ?          ?           ?
#
# ⚠️ DB 크기를 잴 땐 .db 뿐 아니라 -wal 파일도 더해야 합니다.
#    WAL 모드에선 커밋 직후 데이터가 아직 -wal 에 있어서, .db 만 보면
#    "어? 파일이 안 커졌네?" 하게 됩니다. (이것 자체가 WAL 을 이해하는 좋은 실마리)
#
# 💭 측정을 신뢰할 수 있게 만들기
#    · 같은 조건을 3번 재서 중앙값을 쓰세요. 한 번만 재면 다른 프로세스가
#      디스크를 쓰던 순간에 걸려서 이상한 값이 나옵니다.
#    · 맥북은 전원 연결/배터리에 따라 CPU 클럭이 다릅니다. 전원 꽂고 재세요.
#    · 이슈에 "M? 맥북, SSD, Python 3.x, SQLite x.y" 를 각주로 남기세요.
#      "재현 가능한가"는 [로드맵:209] 에 적어둔 예상 질문입니다.


CASES = [
    ("A  매 tick commit",      "naive",     run_naive),
    ("B  전체 1 트랜잭션",       "txn",       run_transaction),
    ("B' 50tick 마다 commit",  "txn50",     run_transaction_periodic),
    ("C  executemany",         "bulk",      run_bulk),
    ("D  5초 샘플링",           "sampled",   run_sampled),
]


def measure(name: str, slug: str, fn) -> dict:
    elapsed, rows, size = [], 0, 0
    for _ in range(REPEAT):
        reset_fleet()                       # ← 매번 같은 로봇 움직임으로 되감기
        engine, path = fresh_engine(slug)   # ← 매번 빈 DB
        gc.collect()
        t0 = time.perf_counter()
        rows = fn(engine)
        elapsed.append(time.perf_counter() - t0)
        size = db_bytes(path)
        engine.dispose()
    sec = median(elapsed)
    return {
        "name": name, "rows": rows, "sec": sec,
        "rows_per_sec": rows / sec,
        "ms_per_tick": sec / TICKS * 1000,
        "db_mb": size / 1024 / 1024,
    }


def main() -> None:
    reset_fleet()
    print(f"python  {sys.version.split()[0]}   sqlite  {sqlite3.sqlite_version}")
    print(f"machine {platform.platform()}")
    print(f"조건    로봇 {ROBOT_COUNT}대 × {TICKS} tick, {REPEAT}회 중앙값, "
          f"WAL, sleep 없음(최대 속도)\n")

    results = []
    for name, slug, fn in CASES:
        print(f"  … {name}", flush=True)
        results.append(measure(name, slug, fn))

    print()
    print(f"{'방식':<24}{'행 수':>10}{'소요(s)':>10}{'행/초':>12}"
          f"{'ms/tick':>10}{'DB(MB)':>9}")
    print("─" * 75)
    for r in results:
        print(f"{r['name']:<24}{r['rows']:>10,}{r['sec']:>10.2f}"
              f"{r['rows_per_sec']:>12,.0f}{r['ms_per_tick']:>10.2f}"
              f"{r['db_mb']:>9.1f}")

    base = results[0]
    print("\n기준(A) 대비 배속")
    for r in results[1:]:
        note = "  ※ 행 수가 다름 — 속도 비교 무의미" if r["rows"] != base["rows"] else ""
        print(f"  {r['name']:<24}{base['sec'] / r['sec']:>6.1f}배{note}")


if __name__ == "__main__":
    main()
