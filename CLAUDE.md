# FleetOps — 에이전트 작업 가이드

실시간 대규모 Fleet 3D 관제 대시보드. **6주 스터디 겸 포트폴리오 프로젝트.**
상세는 [docs/기획서.md](docs/기획서.md), 이번 주 작업은 [docs/2주차-issue.md](docs/2주차-issue.md) 참고.

---

## ⚠️ 작업 방식 (가장 중요 — 반드시 지킬 것)
이건 **학습 스터디 프로젝트**입니다. 목표는 "완성된 코드"가 아니라 **사용자(조혜원)가 직접 만들고 설계를 설명·비판할 수 있게 되는 것**.

- **코드를 통째로 대신 짜주지 마세요.** 개념 설명 + 구조/설정 스캐폴딩 + 막힌 지점 도움까지. 실제 구현은 사용자가 합니다.
- 큰 코드를 줄 때는 **왜 그렇게 하는지 + 트레이드오프 + LLM의 순진한 답이 왜 나쁠 수 있는지**를 같이 설명 (스터디 글감이 됨).
- **사용자 수준**: React/Next.js/TypeScript/Tailwind는 **실무 수준(강함)** → 기초 설명 불필요.
  **FastAPI(살짝 해봄)/SQLModel/WebSocket/SQLite·PostgreSQL/Three.js(R3F)/Docker/CI·CD/GraphQL은 처음** → 개념을 곁들여 설명.
- 응답은 **한국어**로.

## 확정된 결정 (바꾸지 말 것, 사용자가 명시적으로 바꾸라 하기 전엔)
- **도메인(스킨)**: 자율주행 로봇/드론 Fleet (디지털 트윈 스타일). README는 "역량(대용량 실시간 3D·성능)" 중심 서술.
- **백엔드**: 진짜 **FastAPI**로 구현 (mock 아님). 시뮬레이터가 데이터 생성.
- **DB**: **SQLite로 시작(2주차)** → **PostgreSQL 이전(5주차)**. 둘 다 관계형.
- **레포 구조**: 모노레포 X. `frontend/` + `backend/` + 루트 `docker-compose.yml`.
- **배포**: Vercel 안 씀. **Docker + Nginx + GitHub Actions로 직접 배포**(6주차).
- **핵심 성능 원칙**: 실시간 위치는 메모리, DB엔 주기적 배치 저장(매 tick INSERT 금지).

## 스택
- **frontend/**: Vite + React 19 + TypeScript + Jotai + @react-three/fiber + @react-three/drei + Tailwind + Vitest + Testing Library
- **backend/**: FastAPI + SQLModel + uvicorn + websockets · SQLite→PostgreSQL · (stretch) Strawberry GraphQL
- **infra**: Docker / docker-compose · Nginx(서빙) · GitHub Actions

## 시작 전 환경 확인 (첫 작업 시 체크)
- Docker / docker-compose 설치·실행 여부
- Python 버전 & 환경(사용자 머신에 miniconda 있음) — 백엔드용 가상환경/패키지매니저(uv 권장) 정할 것
- Node 버전 & 패키지매니저(pnpm/npm)
- macOS arm64 환경

## 컨벤션
- 커밋 메시지에 **Claude Co-Authored-By 트레일러 절대 추가 금지**.
- 기본 브랜치에서 바로 커밋하지 말고 브랜치 파서 작업.
- 각 주차 작업 후 `docs/`에 스터디 글(설계·AI활용·비판·회고) 정리.

### 브랜치
`week{N}/{주제}` — 예: `week2/backend-skeleton`, `week4/3d-instancing`

### 커밋 메시지 (Conventional Commits)
```
<type>(<scope>): <제목 — 명령형, 마침표 없음>

<본문 — "무엇"보다 "왜". 트레이드오프가 있었으면 그걸 적는다>
```
- **type**: `feat` 기능 / `fix` 버그 / `docs` 문서 / `refactor` 동작 그대로 구조 개선 /
  `perf` 성능 / `test` 테스트 / `chore` 설정·빌드
- **scope**: `backend` / `frontend` / `infra` / 생략(문서·설정)
- 제목은 한국어, 50자 이내.
- **본문에 "왜"를 쓸 것.** 이 프로젝트는 스터디용이라 커밋 히스토리 자체가 사고 과정의 기록이 된다.
  주간 이슈의 Deep Dive를 쓸 때 이 히스토리에서 근거를 긁어온다.

### 커밋 쪼개는 기준
- **한 커밋 = 한 가지 이유의 변경.** "이 커밋을 되돌리면 뭐가 사라지나"가 한 문장으로 답되면 OK.
- 설정 변경 + 기능 구현이 섞이면 나눈다. 문서만 고친 건 항상 따로.
- 리뷰어(=미래의 나)가 diff를 위에서 아래로 읽어 이해되면 잘 쪼갠 것.

## 현재 상태 (2026-07-27)
- 레포 초기화 완료. 원격: `github.com/One-HyeWon/fleet-ops` (public).
- 진행 중: **2주차 백엔드 골격** (`week2/backend-skeleton` 브랜치)
  - [x] 서비스 정의 → ERD 설계 (`docs/ERD.md`)
  - [x] FastAPI + uv 세팅, `/health`, SQLite FK·WAL 설정
  - [x] SQLModel 테이블 3개 (`app/models.py`)
  - [ ] 시뮬레이터 (random walk) ← 다음
  - [ ] WebSocket 브로드캐스트 / REST / 배치 저장 / docker-compose
- 스터디 레포는 별도: `GC-Project-Space/ai-luddite` (코드 아님, Issue + 회고만)
