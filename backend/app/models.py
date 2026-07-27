"""DB 테이블 정의 (SQLModel).

📌 여기는 혜원님이 직접 채우는 파일입니다.
   docs/ERD.md 의 표 3개를 코드로 옮기면 됩니다.

────────────────────────────────────────────────────────────
필요한 문법은 아래 예시가 전부입니다.

    class Robot(SQLModel, table=True):
        __tablename__ = "robots"

        id: int | None = Field(default=None, primary_key=True)
        name: str = Field(unique=True, index=True)
        battery: float
        created_at: datetime = Field(default_factory=utcnow)

  · table=True                 → 실제 DB 테이블로 만들라는 표시
  · Field(primary_key=True)    → 기본키
  · Field(unique=True)         → 중복 금지
  · Field(index=True)          → 인덱스 생성 (검색 빨라짐)
  · Field(foreign_key="robots.id")  → 외래키
  · int | None = None          → NULL 허용 (resolved_at 같은 것)
  · default_factory=...        → 행이 만들어질 때 함수를 불러 기본값 채움

복합 인덱스 (robot_id, recorded_at) 는 Field로는 안 되고 아래처럼 씁니다.

    from sqlalchemy import Index

    class Telemetry(SQLModel, table=True):
        __tablename__ = "telemetry"
        __table_args__ = (
            Index("ix_telemetry_robot_time", "robot_id", "recorded_at"),
        )
        ...
────────────────────────────────────────────────────────────

TODO
  [ ] RobotType   Enum  — robot | drone
  [ ] RobotStatus Enum  — idle | moving | charging | error | offline
  [ ] AlertType   Enum  — low_battery | error | offline
  [ ] Severity    Enum  — info | warning | critical
  [ ] Robot     테이블
  [ ] Telemetry 테이블  (+ 복합 인덱스)
  [ ] Alert     테이블
"""

from datetime import datetime, timezone
from enum import Enum, StrEnum  # noqa: F401

import sqlalchemy as sa
from sqlmodel import Field, SQLModel  # noqa: F401  (아직 안 쓰지만 곧 씀)


def utcnow() -> datetime:
    """지금 시각을 UTC로.

    datetime.utcnow() 는 시간대 정보가 없는(naive) 값이라 파이썬에서 deprecated 됐습니다.
    항상 UTC로 저장하고, 화면에 보여줄 때만 한국 시간으로 변환하세요.
    """
    return datetime.now(timezone.utc)


def enum_column(enum_cls, **kwargs) -> sa.Column:
    """Enum 컬럼을 '의도한 대로' 만들어주는 헬퍼.

    ── 왜 필요한가 ────────────────────────────────────────────
    필드에 Enum을 그냥 쓰면 (`status: RobotStatus`) SQLAlchemy가 기본값대로
    처리하는데, 둘 다 우리가 원하는 게 아닙니다.

      1) 값이 아니라 '멤버 이름'을 저장합니다
             RobotStatus.MOVING = "moving"  →  DB엔 'MOVING' 이 들어감
         그러면 API 응답('moving')과 DB 값('MOVING')이 달라져서,
         나중에 SQL을 직접 짤 때 계속 헷갈립니다.

      2) CHECK 제약을 만들지 않습니다 (SQLAlchemy 1.4부터 기본이 꺼짐)
         → DB에 직접 이상한 값을 꽂아도 안 막힙니다. 3중 방어의 마지막 층이 빔.

    values_callable 로 (1)을, create_constraint 로 (2)를 해결합니다.

    ※ SQLModel 문서엔 안 나오는 동작입니다. SQLModel은 얇은 껍데기이고 실제
      DB 작업은 밑에 깔린 SQLAlchemy가 하기 때문 — 막히면 SQLAlchemy 문서를 보세요.
    ──────────────────────────────────────────────────────────

    사용 예:
        status: RobotStatus = Field(
            default=RobotStatus.IDLE,
            sa_column=enum_column(RobotStatus),
        )
    """
    return sa.Column(
        sa.Enum(
            enum_cls,
            values_callable=lambda e: [m.value for m in e],  # 이름 대신 값을 저장
            create_constraint=True,                          # CHECK 제약 생성
        ),
        nullable=False,
        **kwargs,
    )


class RobotType(StrEnum):
    """StrEnum(파이썬 3.11+)을 쓰는 이유:

      · json.dumps 가 그냥 문자열처럼 처리 → WebSocket으로 바로 내보낼 수 있음
      · f"{RobotType.ROBOT}" 가 "robot" 으로 나옴
        (구식 `class X(str, Enum)` 은 "RobotType.ROBOT" 으로 나와 로그가 지저분해짐)

    왼쪽 이름은 대문자(파이썬 상수 관례), 오른쪽 값이 실제 저장·전송될 문자열.
    """

    ROBOT = "robot"
    DRONE = "drone"


# TODO: RobotStatus, AlertType, Severity Enum 정의
class RobotStatus(StrEnum):
    IDLE = "idle"
    MOVING = "moving"
    CHARGING = "charging"
    ERROR = "error"
    OFFLINE = "offline"


class AlertType(StrEnum):
    LOW_BATTERY = "low_battery"
    ERROR = "error"
    OFFLINE = "offline"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


# TODO: Robot, Telemetry, Alert 테이블 정의
class Robot(SQLModel, table=True):
    __tablename__ = "robots"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    type: RobotType = Field(sa_column=enum_column(RobotType))
    status: RobotStatus = Field(sa_column=enum_column(RobotStatus))
    x: float
    y: float
    z: float
    battery: float
    last_seen_at: datetime | None = Field(default=None)
    updated_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)


class Telemetry(SQLModel, table=True):
    __tablename__ = "telemetry"
    __table_args__ = (
        sa.Index("ix_telemetry_robot_time", "robot_id", "recorded_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    robot_id: int = Field(foreign_key="robots.id")
    x: float
    y: float
    z: float
    battery: float
    speed: float
    heading: float
    status: RobotStatus = Field(sa_column=enum_column(RobotStatus))
    recorded_at: datetime = Field(default_factory=utcnow)


class Alert(SQLModel, table=True):
    __tablename__ = "alerts"

    id: int | None = Field(default=None, primary_key=True)
    robot_id: int = Field(foreign_key="robots.id")
    type: AlertType = Field(sa_column=enum_column(AlertType))
    severity: Severity = Field(sa_column=enum_column(Severity))
    message: str
    created_at: datetime = Field(default_factory=utcnow)
    resolved_at: datetime | None = Field(default=None)
    acknowledged: bool = Field(default=False)
    acknowledged_at: datetime | None = Field(default=None)
