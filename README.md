# FleetOps

실시간 대규모 Fleet 3D 관제 대시보드. 자율주행 로봇·드론 수천 대의 위치를
초당 10회 갱신하며 브라우저에서 3D로 렌더링합니다.

**이 프로젝트가 다루는 것은 "기능"이 아니라 "규모"입니다.**
로봇 1,000대 × 초당 10 tick = 초당 1만 건의 상태 변화를,
어떻게 저장하고 · 어떻게 전송하고 · 어떻게 그릴 것인가.

---

## 지금까지 측정한 것

숫자 없이 "최적화했다"고 쓰지 않는 것이 이 프로젝트의 규칙입니다.
아래는 전부 실측이며, 재현 스크립트가 레포에 있습니다.

| 무엇 | before | after | 근거 |
|---|---|---|---|
| 텔레메트리 쓰기 | ORM `add` 53.6s | `executemany` 9.9s (**5.4배**) | [bench_write.py](backend/scripts/bench_write.py) |
| 이벤트 루프 최악 지연 | 4,000ms | `to_thread` 65ms (**61배**) | [bench_blocking.py](backend/scripts/bench_blocking.py) |
| WebSocket 페이로드 | 251.8 KB/회 | 81.0 KB/회 (**68% 절감**) | [ws.py](backend/app/ws.py) |
| 6분 가동 시 DB | 589 MB (죽음의 나선) | 61 MB (안정) | [config.py](backend/app/config.py) |

측정 환경: M-series 맥북 / macOS 26.6 / Python 3.12.8 / SQLite 3.47.2

### 이 숫자들에서 나온 결론 세 가지

**1. 배치 저장이 빠른 건 `fsync` 때문이 아니다.**
통설은 "매 tick commit 이 느린 이유는 디스크 동기화"입니다. 재보니
커밋 비용은 전체의 **1%** 였고(44.6ms 중 0.4ms), 나머지 99%는 파이썬/ORM
비용이었습니다. 커밋 주기를 1/50로 줄여도 1.2배밖에 안 빨라졌고,
5.4배는 전부 ORM 우회에서 나왔습니다.

**2. 트랜잭션을 무작정 키우면 오히려 느려진다.**
"전부 모았다가 한 번에 commit"은 매 tick commit 보다 **느렸습니다**(0.8배).
60만 객체가 세션에 살아남아 peak RSS 1.3GB. fsync 를 아끼고 메모리로 갚은 셈.

**3. 처리량과 지연은 다른 축이다.**
`executemany` 는 처리량 1위지만, 5초치를 한 번에 넣으면 1.1초간 이벤트 루프가
멈춥니다. 그동안 WebSocket 도 `/health` 도 전부 정지. `asyncio.to_thread` 로
최악 지연을 61배 줄였지만 **p99 는 오히려 나빠졌습니다**(17.7→25.5ms) —
드문 대형 정지를 잦은 소형 지터로 바꾼 거래입니다.

---

## 아키텍처

```
                  ┌──────────── 백엔드 (FastAPI) ────────────┐
                  │                                          │
  시뮬레이터 ──100ms──▶  fleet (메모리)                        │
  (random walk)   │      │                                   │
                  │      ├──▶ WebSocket ──81KB/회──▶ 브라우저   │  ← 실시간
                  │      │                                   │
                  │      └──▶ 버퍼 ──5초마다──▶ SQLite         │  ← 과거
                  │            (1초 샘플링)   (executemany,    │
                  │                          워커 스레드)      │
                  └──────────────────────────────────────────┘
```

**핵심 원칙: 실시간 위치는 메모리, DB엔 주기적 배치 저장.**
"지금 어디 있나"의 진실은 메모리에 있고, DB는 과거 궤적 조회용입니다.
그래서 `GET /robots` 는 메모리를, `GET /robots/{id}/telemetry` 는 DB를 읽습니다.

### 두 개의 손잡이 (헷갈리기 쉬움)

| | 무엇을 정하나 | 잃는 것 |
|---|---|---|
| `BATCH_INTERVAL_SEC` (5초) | 얼마나 **몰아서 쓰나** (버퍼링) | 서버가 죽으면 최대 5초치 |
| `TELEMETRY_SAMPLE_EVERY_TICKS` (10) | 얼마나 **자주 남기나** (샘플링) | 샘플 사이의 움직임 |

버퍼링은 "어떻게 쓰느냐"를, 샘플링은 "얼마나 쓰느냐"를 정합니다.
**버퍼링만으로는 부족합니다** — 매 tick 기록으로 6분 돌렸더니 flush 가
10초→44초로 늘며 143만 행을 폐기했습니다(죽음의 나선). 자세한 계산은
[config.py](backend/app/config.py) 주석에.

---

## 실행

### Docker (권장)

```bash
docker compose up --build
curl localhost:8000/health

# 8000 이 이미 쓰이고 있으면
API_PORT=8010 docker compose up --build
```

`docker compose down` 은 DB를 유지하고, `down -v` 는 볼륨까지 지웁니다.

### 로컬 (uv)

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload
```

### 측정 재현

```bash
cd backend
uv run python -m scripts.bench_write      # 쓰기 전략 5종 비교 (~4분)
uv run python -m scripts.bench_blocking   # 이벤트 루프 지연 (~30초)
```

---

## API

| | 설명 | 읽는 곳 |
|---|---|---|
| `WS /ws/telemetry` | 100ms마다 전체 스냅샷 | 메모리 |
| `GET /robots` | 로봇 목록 (`?status=`, `?limit=`, `?offset=`) | 메모리 |
| `GET /robots/{id}` | 로봇 하나의 현재 상태 | 메모리 |
| `GET /robots/{id}/telemetry` | 과거 궤적 (`?since=`, `?limit=`) | DB |
| `GET /health` | 헬스체크 | — |
| `GET /debug/persistence` | 배치 저장·WS 통계 | — |

### WebSocket 프로토콜

접속하면 **`manifest` 를 한 번** 받고, 이후 **`snapshot` 을 100ms마다** 받습니다.

```jsonc
// 접속 직후 1회 — 변하지 않는 것
{"type": "manifest", "robots": [{"id": 1, "name": "R-001", "kind": "robot"}, ...]}

// 이후 매 tick — 변하는 것만, 반올림해서
{"type": "snapshot", "robots": [{"id": 1, "x": 2.5, "y": 27.5, "z": 0.0,
                                 "h": 190, "b": 79.1, "s": "idle"}, ...]}
```

`name`·`type` 을 매 tick 보내지 않고 소수점을 2자리로 줄인 것이 **68% 절감**의
내용입니다. 대신 프론트가 "id 3번은 R-003" 이라는 상태를 갖게 됩니다 —
무상태 vs 대역폭의 트레이드오프.

**왜 SSE 가 아니라 WebSocket인가**: 지금은 서버→클라 단방향이라 SSE 가 더
적합합니다(자동 재연결이 공짜). 그럼에도 WS 를 고른 것은 Week 03~04 에
**뷰포트 기반 구독**(클라가 카메라 영역을 계속 알려줘야 함)과 **바이너리
프레임**(SSE 는 텍스트 전용 → base64 로 33% 증가)이 필요하기 때문입니다.
판단 기준은 "실시간이냐"가 아니라 "클라가 서버에 계속 말을 거느냐"입니다.

---

## 스택

**backend** FastAPI · SQLModel · uvicorn · SQLite(→ PostgreSQL, Week 05)
**frontend** Vite · React 19 · TypeScript · Jotai · @react-three/fiber · Tailwind *(Week 03~)*
**infra** Docker · Nginx · GitHub Actions *(Week 06)*

## 로드맵

[docs/로드맵.md](docs/로드맵.md) 참고. 6주 스터디 프로젝트이며 매주 측정 결과를
문서로 남깁니다.

| | 주제 | 상태 |
|---|---|---|
| Week 01 | 설계·ERD·시뮬레이터 | ✅ |
| Week 02 | WebSocket · 배치 저장 · REST · Docker | ✅ |
| Week 03 | 프론트 실시간 파이프라인 · 리렌더 최적화 | |
| Week 04 | R3F 3D — 인스턴싱·LOD (draw call 1000 → 1) | |
| Week 05 | PostgreSQL 이전 · 시계열 집계 | |
| Week 06 | Docker + Nginx + Actions 직접 배포 | |

## 알려진 한계

정직하게 적어둡니다.

- **브로드캐스트가 순차 전송**입니다. 느린 클라이언트 하나가 나머지 전원을
  기다리게 하고, tick 루프까지 밀립니다. 클라 20개에서 브로드캐스트 최대
  453ms 를 관측했습니다(tick 주기는 100ms). Week 03 에서 다룹니다.
- **수평 확장 불가**. 상태가 프로세스 메모리에 있어 서버를 2대로 못 늘립니다.
  의도한 선택이며, 늘리려면 Redis 같은 외부 상태 저장소가 필요합니다.
- **SQLite 는 쓰기 락이 하나**입니다. 지금은 쓰는 주체가 배치 하나뿐이라
  문제가 없지만, 그래서 Week 05 에 PostgreSQL 로 갑니다.
- **`fsync` 의 내구성 보장이 약합니다.** macOS 의 `fsync()` 는 드라이브 캐시를
  비우지 않습니다(진짜 배리어인 `F_FULLFSYNC` 는 51배 느림). 텔레메트리
  로그라 감수한 선택이지만, 결제 데이터였다면 켜야 합니다.
