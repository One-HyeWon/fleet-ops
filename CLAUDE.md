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

## 현재 상태 (2026-07-24)
- 아직 **레포 초기화 전**(git init 안 함), 코드 없음. `docs/`에 기획서·2주차 이슈만 있음.
- **1주차(마이그레이션 아키텍처 케이스)는 별도로 완료**. 다음은 **2주차** = 백엔드 골격.
