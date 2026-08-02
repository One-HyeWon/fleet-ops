"""DB 연결 설정.

여기엔 SQLite의 함정 두 개에 대한 대응이 들어 있습니다. 주석을 꼭 읽어보세요.
"""

from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from app.config import DATABASE_URL

# DB 파일을 둘 폴더가 없으면 만들어둠 (sqlite:///./data/fleet.db)
Path("./data").mkdir(exist_ok=True)

engine = create_engine(
    DATABASE_URL,
    echo=False,  # True로 켜면 실행되는 SQL이 전부 로그로 찍힘 (배울 때 켜볼 것!)
    # ⚠️ SQLite 함정 1 — 스레드 검사
    # SQLite는 기본적으로 "커넥션을 만든 스레드에서만 써라"고 막습니다.
    # 우리는 배치 저장을 별도 스레드로 넘길 예정이라 이 검사를 풀어야 합니다.
    connect_args={"check_same_thread": False},
)


# ⚠️ SQLite 함정 2 — 외래키가 기본으로 꺼져 있음
#
# SQLite는 FOREIGN KEY를 선언해도 "조용히 무시"합니다. 존재하지 않는 robot_id로
# telemetry를 넣어도 통과해요. 연결이 새로 열릴 때마다 아래 PRAGMA를 실행해야
# 비로소 진짜로 동작합니다.
#
# 이걸 안 하면 "FK 걸었으니 안전하다"고 믿다가, 5주차 PostgreSQL 이전 때
# 그동안 쌓인 고아 데이터 때문에 마이그레이션이 터집니다.
@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    # WAL(Write-Ahead Logging) 모드: 쓰기를 별도 로그 파일에 덧붙이는 방식.
    # 읽기가 쓰기를 막지 않게 되어, "가끔 몰아 쓰고 자주 읽는" 우리 패턴에 유리합니다.
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def create_db_and_tables() -> None:
    """models.py에 정의된 SQLModel 클래스들로 실제 테이블을 만듭니다.

    이미 있으면 건너뜁니다. 단, "컬럼 추가" 같은 변경은 반영하지 못해요.
    (그걸 제대로 하려면 마이그레이션 도구가 필요합니다 → 5주차 Alembic)
    """
    SQLModel.metadata.create_all(engine)


def get_session():
    """FastAPI 의존성 주입용. 요청 하나당 세션 하나를 열고 끝나면 닫습니다."""
    with Session(engine) as session:
        yield session
