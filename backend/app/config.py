"""프로젝트 설정값.

숫자를 코드 여기저기 흩뿌리지 않고 한곳에 모아둡니다.
성능 측정할 때 ROBOT_COUNT만 바꿔서 1,000 → 5,000으로 늘려볼 수 있어야 하기 때문.
"""

# ── 시뮬레이터 ────────────────────────────────
ROBOT_COUNT = 1000          # 로봇 대수. 성능 측정 시 이 값을 조절
TICK_MS = 100               # 몇 ms마다 상태를 갱신할지 (100ms = 초당 10 tick)
RANDOM_SEED = 42            # 고정하면 매번 같은 움직임 → before/after 비교가 가능해짐

# ── 창고 공간 ────────────────────────────────
WAREHOUSE_SIZE = 100.0      # 100m × 100m 정사각형
MAX_ALTITUDE = 20.0         # 드론 최대 고도(m). 지상 로봇은 항상 z=0

# ── 배치 저장 ────────────────────────────────
BATCH_INTERVAL_SEC = 5      # 몇 초마다 DB에 저장할지
# ↑ 이 값이 "데이터 해상도"이자 "장애 시 유실량"

# ── 알림 판정 규칙 ───────────────────────────
LOW_BATTERY_THRESHOLD = 20.0        # 이 아래로 떨어지면 warning
CRITICAL_BATTERY_THRESHOLD = 5.0    # 이 아래로 떨어지면 critical
OFFLINE_TIMEOUT_SEC = 5.0           # 마지막 신호 후 이 시간이 지나면 offline 판정

# ── DB ───────────────────────────────────────
DATABASE_URL = "sqlite:///./data/fleet.db"
