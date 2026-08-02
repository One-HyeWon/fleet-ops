"""메모리에 들고 있는 실시간 Fleet 상태.

📌 여기는 혜원님이 채우는 파일입니다.

════════════════════════════════════════════════════════════
이 파일에 만들 것 3개

  ① RobotState   "로봇 한 대의 상태는 이런 모양이다" 라는 틀 (dataclass)
                 → 서류 양식 한 장이라고 생각
                   빈칸: 위치, 배터리, 방향, 상태 …

  ② fleet        그 서류 1,000장을 번호순으로 꽂아둔 서랍 (dict)
                 → fleet[500] 하면 500번 로봇 서류가 바로 나옴

  ③ init_fleet() 서버가 켜질 때 서랍에 서류 1,000장을 만들어 채우는 함수
                 → 딱 한 번만 실행됨

  이후 시뮬레이터는 100ms마다 서랍을 열어 1,000장의 숫자를 조금씩 고칩니다.
  WebSocket은 같은 서랍을 읽어서 브라우저로 보냅니다. DB는 5초에 한 번만 봅니다.
════════════════════════════════════════════════════════════

왜 DB가 아니라 메모리인가
  로봇 1,000대 × 초당 10 tick = 초당 1만 번 갱신입니다.
  이걸 매번 DB에 쓰면 죽습니다. "지금 이 순간"은 이 파일 안에만 있고,
  DB에는 5초마다 스냅샷만 저장합니다.

models.py 의 Robot 과 뭐가 다른가
  같은 로봇을 가리키지만 쓰임새가 다릅니다.

      RobotState (여기, 메모리)      Robot (models.py, DB)
      ──────────────────────       ─────────────────────
      100ms마다 바뀜                5초마다 갱신
      서버 끄면 사라짐                디스크에 남음
      검증 안 함 (그래서 빠름)         검증·제약 있음

  왜 SQLModel 객체를 메모리 상태로 쓰지 않는가:
    1. 세션에 붙은 객체는 필드를 바꿀 때마다 ORM이 변경을 추적한다.
       초당 수만 번 바꾸는 값에 이게 붙으면 낭비고, 의도치 않은 시점에
       DB로 새어나갈 수 있다.
    2. SQLModel은 Pydantic이라 값을 대입할 때마다 "이거 float 맞아?"를 검사한다.
       그런데 그 값은 방금 우리가 계산한 숫자다 — 내가 만든 걸 내가 검사하는 헛수고.
       (검증은 바깥에서 온 데이터에 하는 것이지, 내부 계산 결과에 하는 게 아니다)
    3. 관심사가 다르다. DB 모델엔 created_at 처럼 시뮬레이션과 무관한 게 있고,
       메모리 상태엔 heading 처럼 매 tick 쓰지만 매번 저장할 필요는 없는 게 있다.

────────────────────────────────────────────────────────────
TODO
  [ ] ① RobotState dataclass
  [ ] ② fleet dict
  [ ] ③ init_fleet()
────────────────────────────────────────────────────────────
"""

import random

from dataclasses import dataclass  # noqa: F401
from datetime import datetime  # noqa: F401

from app.models import RobotStatus, RobotType, utcnow
from app.config import MAX_ALTITUDE, RANDOM_SEED, ROBOT_COUNT, WAREHOUSE_SIZE  # noqa: F401


# ─────────────────────────────────────────────────────────
# ① RobotState — 로봇 한 대의 상태를 담는 틀
# ─────────────────────────────────────────────────────────
#
# dataclass 문법:
#
#     @dataclass(slots=True)
#     class RobotState:
#         id: int              ← 반드시 타입을 써야 합니다.
#         x: float                ": float" 를 빼면 필드로 인식되지 않아요.
#
# 이렇게 정의해두면 이렇게 씁니다:
#
#     r = RobotState(id=1, x=12.5, ...)
#     r.x = 13.0                  # 값 바꾸기
#
# slots=True 는 뭔가:
#   파이썬 객체는 기본적으로 속성을 dict에 담아둡니다(유연하지만 무거움).
#   slots=True 를 붙이면 "이 클래스는 정의된 칸만 갖는다"고 못 박아서
#   메모리를 덜 쓰고 속성 접근이 빨라집니다.
#   1,000대에선 티가 안 나지만 5,000대 성능 측정 때 의미가 생깁니다.
#   덤으로, 정의에 없는 속성을 실수로 만들면 바로 에러가 납니다(오타 방지).
#
# 담을 필드 (docs/ERD.md 참고):
#     id, name, type, x, y, z, heading, speed, battery, status, last_seen_at
#
# 💭 생각해볼 것: models.py 의 Robot 에는 created_at 이 있는데
#    여기엔 왜 필요 없을까요? (힌트: 시뮬레이터가 그 값을 쓸 일이 있나?)
# Answer: created_at은 로봇이 생성된 시점을 기록하는 필드로, 데이터베이스에서 로봇의 생성 시간을 추적하는 데 사용됩니다. 그러나 RobotState는 메모리 내에서 실시간으로 로봇의 상태를
# 나타내는 객체이므로, 로봇이 언제 생성되었는지에 대한 정보는 필요하지 않습니다. RobotState는 주로 현재 위치, 배터리 상태, 속도 등과 같은 동적인 정보를 다루기 때문에,
# 생성 시간과 같은 정적인 정보는 포함할 필요가 없습니다.

# TODO: RobotState 정의
@dataclass(slots=True)
class RobotState:
    id: int
    name: str
    type: RobotType
    x: float
    y: float
    z: float
    heading: float
    speed: float
    battery: float
    status: RobotStatus
    last_seen_at: datetime | None = None

# ─────────────────────────────────────────────────────────
# ② fleet — 로봇 상태를 id로 찾을 수 있게 모아둔 것
# ─────────────────────────────────────────────────────────
#
#     fleet: dict[int, RobotState] = {}
#            └─ 키는 로봇 id(int), 값은 RobotState
#
# 쓰는 법:
#     fleet[500]                    # 500번 로봇 상태
#     fleet[500].battery = 86.0     # 그 로봇 배터리 수정
#     for r in fleet.values(): ...  # 전체 순회
#
# 리스트가 아니라 dict 인 이유:
#   "3번 로봇 갱신"이 초당 수천 번 일어납니다.
#   리스트면 매번 처음부터 훑어야 하고(1,000개면 평균 500번 비교),
#   dict는 키로 한 번에 찾습니다.
#
# 이 dict 하나를 시뮬레이터가 쓰고, WebSocket과 REST가 읽습니다.
# 같은 프로세스 안이라 import 만 하면 그냥 공유됩니다.
# (시뮬레이터를 별도 프로세스로 안 띄우는 이유가 이것)


rng = random.Random(RANDOM_SEED)

# TODO: fleet 선언
fleet: dict[int, RobotState] = {}


# ─────────────────────────────────────────────────────────
# ③ init_fleet() — 서버 시작 시 로봇 1,000대를 만들어 fleet에 채운다
# ─────────────────────────────────────────────────────────
#
#     def init_fleet() -> None:
#         for i in range(1, ROBOT_COUNT + 1):
#             fleet[i] = RobotState(id=i, name=..., ...)
#
# 채울 때 신경 쓸 것:
#   · 이름  "R-001" 형식  →  f"R-{i:03d}"  (숫자를 3자리로, 앞을 0으로 채움)
#   · 위치  창고 안 아무 데나  →  rng.uniform(0, WAREHOUSE_SIZE)
#   · 종류  10% 정도만 drone, 나머지 robot
#   · 배터리  50~100 사이 랜덤
#            ⚠️ 전부 100으로 시작하면 1,000대가 동시에 방전돼서
#               충전 타이밍이 한꺼번에 몰립니다. 흩어놓아야 자연스러워요.
#   · 상태  처음엔 대부분 idle 로 시작
#   · rng 는 simulator.py 의 것을 import 해서 쓰세요 (시드 고정 유지)

# TODO: init_fleet() 정의
def init_fleet() -> None:
    for i in range(1, ROBOT_COUNT + 1):
        robot_type = RobotType.DRONE if rng.random() < 0.1 else RobotType.ROBOT
        fleet[i] = RobotState(
            id=i,
            name=f"R-{i:03d}",
            type=robot_type,
            x=rng.uniform(0, WAREHOUSE_SIZE),
            y=rng.uniform(0, WAREHOUSE_SIZE),
            z=rng.uniform(
                0, MAX_ALTITUDE) if robot_type == RobotType.DRONE else 0.0,
            heading=rng.uniform(0, 360),
            speed=0.0,
            battery=rng.uniform(50, 100),
            status=RobotStatus.IDLE,
            last_seen_at=utcnow(),
        )
