"""FastAPI 앱 진입점."""

from fastapi import FastAPI

app = FastAPI(title="FleetOps API")


@app.get("/health")
def health():
    """서버가 살아 있는지 확인하는 용도.

    Docker나 배포 환경이 "이 컨테이너 정상인가?"를 물어볼 때 쓰는 관례적인 엔드포인트입니다.
    """
    return {"status": "ok"}


# TODO(2주차)
#   [ ] lifespan 등록 — 앱이 뜰 때 테이블 생성 + 시뮬레이터 루프 시작
#   [ ] GET  /robots
#   [ ] GET  /robots/{id}/telemetry
#   [ ] WS   /ws/telemetry
