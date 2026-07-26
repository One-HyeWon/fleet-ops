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
from enum import Enum

from sqlmodel import Field, SQLModel  # noqa: F401  (아직 안 쓰지만 곧 씀)


def utcnow() -> datetime:
    """지금 시각을 UTC로.

    datetime.utcnow() 는 시간대 정보가 없는(naive) 값이라 파이썬에서 deprecated 됐습니다.
    항상 UTC로 저장하고, 화면에 보여줄 때만 한국 시간으로 변환하세요.
    """
    return datetime.now(timezone.utc)


class RobotType(str, Enum):
    """str을 같이 상속하는 이유: JSON 직렬화가 자동으로 됩니다.
    그냥 Enum만 상속하면 WebSocket으로 내보낼 때 직렬화 에러가 나요.
    """

    ROBOT = "robot"
    DRONE = "drone"


# TODO: RobotStatus, AlertType, Severity Enum 정의


# TODO: Robot, Telemetry, Alert 테이블 정의
