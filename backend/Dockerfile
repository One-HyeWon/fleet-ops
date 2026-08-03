# FleetOps 백엔드 이미지
#
# ── 왜 이렇게 생겼나 ────────────────────────────────────────
# Docker 빌드는 위에서 아래로 층(layer)을 쌓고, 각 층을 캐시합니다.
# 어떤 층이 바뀌면 그 아래 전부가 다시 빌드됩니다.
#
#   ❌ 순진한 방법
#         COPY . .
#         RUN uv sync
#      → 코드를 한 글자만 고쳐도 의존성 설치를 처음부터 다시 합니다.
#        매 빌드 수십 초씩 날아갑니다.
#
#   ✅ 자주 안 바뀌는 것을 먼저 복사
#         COPY pyproject.toml uv.lock ./     ← 의존성이 바뀔 때만 무효화
#         RUN uv sync
#         COPY app ./app                     ← 코드는 여기서
#      → 코드만 고치면 마지막 층만 다시 만듭니다.
#
# 6주차에 프론트엔드에서 **멀티스테이지 빌드**(빌드 도구를 최종 이미지에서
# 빼는 것)를 하게 되는데, 그 전 단계 개념이 이 "층 순서"입니다.
# ────────────────────────────────────────────────────────────

FROM python:3.12-slim

# uv 를 공식 이미지에서 바이너리만 꺼내 옵니다.
# (pip install uv 보다 빠르고, 파이썬 환경을 건드리지 않습니다)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# ── 층 1: 의존성 (pyproject.toml / uv.lock 이 바뀔 때만 다시 실행) ──
COPY pyproject.toml uv.lock ./
# --frozen : uv.lock 을 그대로 따르고 갱신하지 않음.
#            "내 노트북에선 됐는데 서버에선 안 되는" 상황의 주범이
#            버전이 조용히 달라지는 것이라, 배포용은 항상 lock 을 고정합니다.
# --no-install-project : 아직 코드를 안 복사했으므로 프로젝트 자체는 빼고 설치
RUN uv sync --frozen --no-install-project --no-dev

# ── 층 2: 코드 (여기부터는 자주 바뀜) ──────────────────────
COPY app ./app
COPY scripts ./scripts

# SQLite 파일이 놓일 자리. compose 에서 볼륨으로 덮어씁니다.
RUN mkdir -p /app/data

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1
# ↑ PYTHONUNBUFFERED: 파이썬이 stdout 을 버퍼링하면 컨테이너 로그가
#   한참 뒤에 몰아서 나옵니다. 로그를 실시간으로 보려면 꺼야 합니다.

EXPOSE 8000

# --host 0.0.0.0 이 필수입니다.
# 기본값(127.0.0.1)은 "컨테이너 안에서만" 접속 가능하다는 뜻이라
# 호스트에서 포트를 열어도 연결이 안 됩니다. 흔한 함정.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
