"""텔레메트리 시뮬레이터 — 로봇 1,000대를 '연기'하는 백그라운드 루프.

📌 여기는 혜원님이 채우는 파일입니다.

────────────────────────────────────────────────────────────
이 파일은 FastAPI와 아무 상관 없는 평범한 파이썬 코드입니다.
그냥 while 루프예요. FastAPI 없이도 혼자 돕니다.

다만 같은 프로세스 안에서 같이 띄웁니다(main.py 의 lifespan).
그래야 이 루프가 갱신한 state.fleet 을 WebSocket이 바로 읽을 수 있습니다.

  현실이라면:  [진짜 로봇 1,000대] ──무선──▶ [서버]
  우리:        [이 파일의 루프]   ──메모리──▶ [서버]
────────────────────────────────────────────────────────────

TODO
  [ ] step_robot(r)      — 로봇 한 대를 한 tick 만큼 진행
  [ ] tick()             — 전체 로봇 1회 갱신
  [ ] run_simulator()    — 무한 루프 (drift 보정 포함)
"""

import asyncio  # noqa: F401
import math  # noqa: F401

from app.config import (  # noqa: F401
    LOW_BATTERY_THRESHOLD,
    MAX_ALTITUDE,
    TICK_MS,
    WAREHOUSE_SIZE,
)
from app.persistence import record
from app.state import RobotState, fleet, rng
from app.ws import manager
from app.models import RobotStatus, RobotType, utcnow  # noqa: F401

# ⚠️ import 방향에 주의
#
#     config.py       ← 아무것도 import 안 함        (맨 아래층)
#        ↑
#     state.py        ← config 만
#        ↑
#     persistence.py  ← config + state + db        (버퍼에 쌓기만)
#     ws.py           ← state 만                    (같은 층. 서로 모름)
#        ↑
#     simulator.py    ← 위의 것들                   (여기)
#        ↑
#     main.py         ← 전부                        (맨 위층)
#
# 화살표가 한 방향으로만 흘러야 합니다. state.py 가 여기서 뭔가를 import 하면
# 서로를 기다리다 ImportError 가 납니다(순환 참조).
# 그래서 rng 는 state.py 에 두고 여기서 가져다 씁니다.


# TODO: step_robot(r: RobotState) -> None
#
#   로봇 한 대를 100ms 만큼 진행시킵니다. 규칙:
#
#   1) 방향(heading)을 조금만 흔든다  ← ★ 여기가 핵심
#        r.heading = (r.heading + rng.uniform(-5, 5)) % 360
#
#      순진한 방법은 위치를 직접 흔드는 것입니다:
#            x += rng.uniform(-1, 1)
#            y += rng.uniform(-1, 1)
#      이러면 매 tick 방향이 새로 뽑혀서 제자리에서 부들부들 떨기만 합니다.
#      로봇이 아니라 먼지 입자처럼 보여요(실제로 이건 브라운 운동 모델입니다).
#      방향에 '관성'을 주면 한동안 같은 쪽으로 가서 부드러운 곡선이 나옵니다.
#      그리고 heading 컬럼이 공짜로 나옵니다 — 따로 지어낼 필요가 없어요.
#
#   2) 그 방향으로 전진
#        math 는 라디안을 쓰므로 math.radians(r.heading) 로 변환할 것
#        x += speed * sin(rad)
#        y += speed * cos(rad)
#        (speed 는 m/s, tick 은 0.1초 → 실제 이동거리는 speed * 0.1)
#
#   3) 경계 반사 — 0 ~ WAREHOUSE_SIZE 를 벗어나려 하면 당구공처럼 튕긴다
#        벗어난 좌표를 안으로 되돌리고 heading 을 반대쪽으로
#
#   4) 배터리 — status 에 따라 다른 속도로 감소
#        moving 이면 빨리, idle 이면 천천히
#
#   5) 상태 전이 (작은 상태 머신)
#        battery < LOW_BATTERY_THRESHOLD  →  charging (속도 0)
#        charging 중이면 배터리 회복, 100% 되면 → idle
#        아주 낮은 확률로 error (알림 테스트용)
#        idle 이 잠시 지속되면 → moving
#
#   6) last_seen_at 갱신 (지금 신호를 받았다는 뜻)
#
#   7) 드론이면 z 도 조금씩 변화 (0 ~ MAX_ALTITUDE)
def step_robot(r: RobotState) -> None:
    # 1) 방향 흔들기
    r.heading = (r.heading + rng.uniform(-5, 5)) % 360

    # 2) 전진
    rad = math.radians(r.heading)
    distance = r.speed * (TICK_MS / 1000)
    r.x += distance * math.sin(rad)
    r.y += distance * math.cos(rad)

    # 3) 경계 반사
    # x(동서) 벽 → 좌우 성분만 뒤집기
    if r.x < 0:
        r.x = -r.x
        r.heading = (-r.heading) % 360
    elif r.x > WAREHOUSE_SIZE:
        r.x = 2 * WAREHOUSE_SIZE - r.x
        r.heading = (-r.heading) % 360

    # y(남북) 벽 → 앞뒤 성분만 뒤집기
    if r.y < 0:
        r.y = -r.y
        r.heading = (180 - r.heading) % 360
    elif r.y > WAREHOUSE_SIZE:
        r.y = 2 * WAREHOUSE_SIZE - r.y
        r.heading = (180 - r.heading) % 360

    # 4) 배터리 감소
    if r.status == RobotStatus.MOVING:
        r.battery -= rng.uniform(0.1, 0.5)
    elif r.status == RobotStatus.IDLE:
        r.battery -= rng.uniform(0.01, 0.05)

    # 5) 상태 전이 — 현재 상태로 먼저 분기
    if r.status == RobotStatus.CHARGING:
        r.battery = min(100.0, r.battery + rng.uniform(0.5, 1.0))
        if r.battery >= 100.0:
            r.status = RobotStatus.IDLE

    elif r.status == RobotStatus.ERROR:
        if rng.random() < 0.005:          # 가끔 복구 (사람이 고쳤다고 치고)
            r.status = RobotStatus.IDLE

    elif r.battery < LOW_BATTERY_THRESHOLD:
        r.status = RobotStatus.CHARGING
        r.speed = 0.0

    elif rng.random() < 0.00001:          # 아주 드물게 고장
        r.status = RobotStatus.ERROR
        r.speed = 0.0

    elif r.status == RobotStatus.IDLE and rng.random() < 0.01:
        r.status = RobotStatus.MOVING
        r.speed = rng.uniform(0.5, 2.0)

    # 6) last_seen_at 갱신
    r.last_seen_at = utcnow()

    # 7) 드론이면 z 변화
    if r.type == RobotType.DRONE:
        r.z += rng.uniform(-0.5, 0.5)
        r.z = max(0, min(MAX_ALTITUDE, r.z))


# TODO: tick() -> None
#
#   fleet 의 모든 로봇에 step_robot 을 한 번씩 적용합니다.
#   지금은 그냥 for 루프면 충분합니다.
def tick() -> None:
    for r in fleet.values():
        step_robot(r)


# TODO: run_simulator() -> None  (async 함수)
#
#   무한히 도는 루프. 여기에 함정이 하나 있습니다.
#
#   ❌ 순진한 버전
#         while True:
#             tick()                      # 20ms 걸림
#             await asyncio.sleep(0.1)    # 100ms 쉼
#                                         # → 실제 주기는 120ms!
#
#      로봇이 늘어나 tick() 이 50ms 걸리면 150ms가 됩니다.
#      부하에 따라 주기가 고무줄처럼 늘어나요. "초당 10 tick" 이 기준인
#      프로젝트에서 이러면 모든 성능 수치가 흔들립니다.
#
#   ✅ 목표 시각을 미리 정해두고 '남은 시간만' 자기
#         start = loop.time()
#         n = 0
#         while True:
#             tick()
#             n += 1
#             target = start + n * (TICK_MS / 1000)
#             await asyncio.sleep(max(0, target - loop.time()))
#
#      · loop.time() 은 asyncio 의 단조 시계(monotonic clock)입니다.
#        시스템 시간이 바뀌어도 뒤로 안 갑니다.
#      · max(0, ...) 인 이유: tick 이 100ms 보다 오래 걸리면 음수가 되는데,
#        sleep 에 음수를 넣을 수 없고 그 상황은 "이미 밀렸다"는 뜻입니다.
#        (그때는 경고 로그를 남기면 좋습니다 — 성능 한계를 발견하는 신호)
#
#   ⚠️ time.sleep() 을 쓰면 안 됩니다. 그 100ms 동안 이벤트 루프 전체가 멈춰서
#      WebSocket도 /health도 응답하지 못합니다. 반드시 await asyncio.sleep().
async def run_simulator() -> None:
    loop = asyncio.get_running_loop()
    start = loop.time()
    n = 0
    while True:
        tick()
        record()                            # 배치 버퍼에 쌓기 (DB엔 안 씀)
        await manager.broadcast_snapshot()  # 접속자에게 밀어넣기
        n += 1
        target = start + n * (TICK_MS / 1000)
        await asyncio.sleep(max(0, target - loop.time()))
