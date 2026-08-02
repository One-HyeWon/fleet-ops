# Week 01 이슈 리뷰 답변 초안

> 📌 [ai-luddite#4](https://github.com/GC-Project-Space/ai-luddite/issues/4) 에 달 댓글 초안.
> 리뷰어(@luke0408) 질문 2개에 대한 답변. 검토 후 등록.
>
> **받은 질문**
> 1. DB를 관리하는 라이브러리 의존성이 SQLite, SQLModel, SQLAlchemy 3가지가 보이는데 왜 3가지가 다 필요했는지
> 2. 왜 비즈니스 로직 레이어에도 ENUM이 있는데 DB 레벨에서 ENUM이 추가로 필요하다 판단했는지

---

두 질문 다 답하면서 제가 몰랐던 걸 두 개 발견했습니다. 감사합니다.

---

## 1. 왜 SQLite / SQLModel / SQLAlchemy 세 개가 다 필요했는가

**결론부터 말하면 세 개를 고른 적이 없습니다. 하나를 골랐더니 셋이 됐습니다.**

먼저 셋은 같은 층이 아닙니다.

| | 정체 | 어떻게 들어왔나 |
|---|---|---|
| **SQLite** | **DBMS** (라이브러리가 아님) | 설치한 적 없음 — 파이썬 표준 라이브러리에 `sqlite3` 드라이버가 내장 |
| **SQLModel** | ORM + 검증 래퍼 | **유일하게 선택한 것** |
| **SQLAlchemy** | 실제 ORM 엔진 | SQLModel의 전이 의존성 |

`pyproject.toml`에 적은 건 `sqlmodel` 한 줄입니다.

```
$ uv tree
fleetops-backend
├── sqlmodel v0.0.39
│   ├── pydantic v2.13.4
│   └── sqlalchemy v2.0.51    ← 딸려온 것
```

프론트로 치면 `npm install next` 했더니 `react`가 들어온 것과 같은 구조입니다. Next를 골랐지 React를 고른 게 아니지만, `useState`를 쓰는 순간 그건 React 것이죠.

### SQLite를 고른 이유

이건 근거가 뚜렷합니다. 기획서에 *"가벼운 관계형 → 프로덕션 관계형 **이전 경험**"* 이라고 적어뒀습니다. 5주차에 PostgreSQL로 옮기면서 동시성 모델 차이(파일 락 vs MVCC), 타입 시스템 차이를 직접 겪는 게 목적입니다. 처음부터 Postgres로 갔으면 그 주차가 통째로 사라집니다.

부수적으로 초반엔 Docker 없이 파일 하나로 시작할 수 있어서 좋았습니다.

### SQLModel을 고른 이유 — 정직하게는, 대안을 비교하지 않았습니다

들 수 있는 근거는 있습니다. FastAPI를 만든 사람이 만들었고, 원래 두 벌 써야 하는 걸 한 클래스로 합쳐줍니다.

```python
# SQLModel 없이 = 같은 구조를 두 번
class RobotTable(Base): ...        # SQLAlchemy — 테이블
class RobotSchema(BaseModel): ...  # Pydantic   — API 검증

# SQLModel = 한 번
class Robot(SQLModel, table=True): ...
```

다 사실이고 실제로 편했지만, **선택 시점에 Tortoise ORM이나 SQLAlchemy 직접 사용과 비교한 건 아닙니다.** 기획 단계에서 "FastAPI 생태계 표준"이라는 이유로 정해둔 걸 그대로 썼습니다.

### 그런데 질문 받고 코드를 다시 보니 — SQLAlchemy를 직접 쓰고 있었습니다

세 군데에서 SQLModel을 뚫고 내려갔습니다.

| 위치 | 코드 | 왜 내려갔나 |
|---|---|---|
| `models.py` | `sa.Index("ix_telemetry_robot_time", "robot_id", "recorded_at")` | SQLModel의 `Field(index=True)`는 **단일 컬럼 인덱스만** 만듭니다. 복합 인덱스를 표현할 문법이 없습니다 |
| `models.py` | `sa.Column(sa.Enum(..., values_callable=..., create_constraint=True))` | SQLModel은 `status: RobotStatus` 로만 쓸 수 있어 **옵션을 줄 자리가 없습니다** |
| `db.py` | `@event.listens_for(Engine, "connect")` → `PRAGMA foreign_keys=ON` | SQLModel엔 **연결 생명주기 훅이 없습니다** |

셋 다 곁가지가 아니라 이번 주 작업의 핵심(복합 인덱스 / 데이터 무결성 / FK 활성화)이었습니다.

**그리고 `sqlalchemy`를 직접 import하면서 `pyproject.toml`에는 선언하지 않았습니다.** 지금은 SQLModel이 끌고 와서 돌아가지만, SQLModel이 의존성을 바꾸면 제 코드가 조용히 깨집니다. 직접 import하는 건 직접 선언해야 하는 게 맞으니 반영하겠습니다.

### 그래서 지금 시점의 평가

이슈 본문에 쓴 사건(Enum이 값이 아니라 이름으로 저장됨 / CHECK 제약이 안 생김)의 원인도 정확히 여기였습니다. **제가 고른 건 SQLModel인데, 제 데이터가 저장되는 방식을 결정한 건 고르지 않은 SQLAlchemy의 기본값이었습니다.**

> SQLModel은 SQLAlchemy를 **몰라도 되게 해준 게 아니라, 배우는 시점을 미뤄준 것**이었다.
> 그 청구서가 복합 인덱스·CHECK 제약·PRAGMA 세 번에 걸쳐 돌아왔다.

다시 고른다면 그래도 SQLModel을 쓸 것 같습니다. 보일러플레이트 감소는 실제 이득이었으니까요. 다만 "추상화를 얹었으니 아래를 안 봐도 된다"는 기대는 버렸고, `echo=True`로 생성되는 SQL을 확인하는 걸 이 조합을 쓰는 비용으로 보게 됐습니다.

---

## 2. 애플리케이션에 이미 있는데 왜 DB 레벨에도 걸었는가

먼저 이건 **기본값이 아니라 명시적으로 켠 것**이 맞습니다.

```python
sa.Enum(enum_cls, create_constraint=True)
#                 └─ SQLAlchemy 1.4부터 기본값은 False
```

가만히 뒀으면 DB엔 아무 제약도 없었습니다.

### 판단 근거 — 두 층이 커버하는 경로가 다르다고 봤습니다

| 값이 DB에 들어가는 경로 | 파이썬 Enum | DB 제약 |
|---|---|---|
| FastAPI 요청 | ✅ | ✅ |
| 내 파이썬 코드 (시뮬레이터 등) | ✅ | ✅ |
| `sqlite3`/`psql`로 직접 UPDATE | ❌ | ✅ |
| **마이그레이션 스크립트** | ❌ | ✅ |
| seed·백필 스크립트의 raw SQL | ❌ | ✅ |
| 나중에 다른 서비스가 같은 DB에 붙을 때 | ❌ | ✅ |

파이썬 Enum은 **제 애플리케이션 코드를 통과하는 경로만** 지킵니다. 아래 네 줄은 파이썬을 안 거칩니다.

특히 저는 **5주차에 SQLite → PostgreSQL 이전이 예정돼 있고, 그 데이터 이동은 ORM을 거치지 않습니다.** 그 순간 파이썬 Enum은 아무 역할도 못 합니다.

비슷한 걸 이번 주에 이미 겪었습니다. SQLite는 **FK 제약이 기본으로 꺼져 있어서** 선언해도 조용히 무시하는데, `PRAGMA foreign_keys=ON`을 안 켰다면 존재하지 않는 `robot_id`로 telemetry가 쌓였을 겁니다. 그때도 파이썬 쪽은 아무것도 못 막았을 겁니다.

정리하면 이렇게 생각했습니다.

> "이 컬럼이 가질 수 있는 값"은 **데이터 자체의 성질**이지 특정 애플리케이션의 성질이 아니다.
> 코드는 배포마다 바뀌고 여러 버전이 동시에 뜰 수도 있지만, 데이터는 한 곳에 오래 남는다.

### 중복 선언은 아닙니다 — 값의 출처는 한 곳입니다

`'idle'`, `'moving'` 같은 문자열을 두 번 적은 곳은 없습니다.

```python
class RobotStatus(StrEnum):          # ← 값 목록은 여기 한 곳
    IDLE = "idle"
    MOVING = "moving"
    ...

sa.Enum(
    enum_cls,
    values_callable=lambda e: [m.value for m in e],   # ← 위에서 값을 뽑아 DB 제약 생성
    create_constraint=True,
)
```

DB의 CHECK는 파이썬 Enum을 **읽어서 파생된 것**입니다. **한 곳에 정의하고 두 곳에서 강제하는 구조**라, 두 층이 어긋날 소스 자체가 없습니다.

### 인정하는 비용, 그리고 조건

남는 비용은 하나입니다. **값을 추가하면 DDL 변경(마이그레이션)이 필요합니다.** 파이썬 Enum만 있었으면 코드 배포로 끝났을 일이죠.

그래서 이건 무조건적인 선택이 아니라 조건부입니다.

- **값이 자주 바뀌는 도메인이었다면 애플리케이션에만 뒀을 겁니다.** 운영 중 DDL 변경은 부담이 큽니다.
- 애플리케이션이 DB의 유일한 사용자이고 팀 규율이 확실하다면, 파이썬 Enum만으로도 충분하다고 봅니다.
- 로봇 상태 5개(대기·이동·충전·고장·연결끊김)는 도메인상 고정적이라 변경 빈도가 낮고, 그래서 얻는 게 크다고 판단했습니다.

### 질문 덕에 발견한 것 — 5주차에 문제가 될 뻔했습니다

답변을 쓰면서 `sa.Enum`이 DBMS마다 다르게 번역된다는 걸 다시 확인했는데, 제가 놓친 게 있었습니다.

| DBMS | `sa.Enum`이 만드는 것 |
|---|---|
| SQLite (현재) | `VARCHAR(8)` + `CHECK (status IN (...))` |
| **PostgreSQL (5주차)** | **`CREATE TYPE robotstatus AS ENUM (...)`** ← 네이티브 ENUM |

즉 지금 코드 그대로 Postgres로 가면 **네이티브 ENUM 타입이 자동으로 생깁니다.** 그건 제가 의도한 게 아닙니다.

네이티브 ENUM은 값 추가에 `ALTER TYPE ... ADD VALUE`가 필요하고 **삭제는 사실상 불가능**합니다(값이 내부 번호로 저장돼 있어서, 지우면 그 값을 가진 기존 행이 가리킬 곳을 잃습니다. 새 타입을 만들고 모든 컬럼을 옮기는 수밖에 없습니다). 제가 CHECK를 택한 이유였던 "유연함"이 그 시점에 사라지는 셈입니다.

막으려면 `native_enum=False` 한 줄이면 되는데, 아직 어느 쪽으로 갈지 정하지 못했습니다.

- **막는다**: 5주차에도 지금과 같은 TEXT + CHECK 구조가 유지돼서, 이전 작업이 스키마 변경 없이 끝납니다.
- **그냥 둔다**: 네이티브 ENUM을 직접 겪어볼 수 있습니다. 이 프로젝트가 학습 목적이라, "값 하나 지우려니 이래서 힘들더라"를 5주차 사례로 삼는 것도 나쁘지 않다고 생각합니다.

지금 기울어 있는 쪽은 후자입니다. 어차피 5주차 주제가 "SQLite와 Postgres의 차이를 직접 겪기"인데, **DBMS에 따라 같은 코드가 다른 스키마를 만든다는 것 자체가 그 차이의 좋은 사례**라서요. 다만 그건 "몰라서 당하는 것"이 아니라 "알고 두는 것"이어야 하니, 이 질문 덕에 미리 알게 된 게 다행입니다.

혹시 이 부분에 의견 있으시면 듣고 싶습니다.
