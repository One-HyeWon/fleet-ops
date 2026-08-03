"""WebSocket 브로드캐스트 — 실시간 텔레메트리를 접속한 클라이언트에게 밀어넣는다.

════════════════════════════════════════════════════════════
REST와 뭐가 다른가
  REST : 요청이 오면 응답하고 끝. 서버는 아무것도 기억하지 않는다.
  WS   : 연결이 계속 살아 있다. 그래서 "누가 접속 중인지"를 서버가 기억해야 한다.
         이 파일이 존재하는 이유가 그것.

왜 SSE 가 아니라 WS 인가 (Week 02 에서 실제로 검토한 것)
  지금 만드는 것만 보면 SSE 가 맞습니다. 서버→클라 단방향이고,
  SSE 는 브라우저가 자동 재연결까지 해줍니다(WS 는 직접 짜야 함).
  그럼에도 WS 를 고른 이유는 **Week 03~04** 에 있습니다.
    · 뷰포트 기반 구독 — 로봇이 늘면 "지금 카메라에 보이는 것만" 보내야 하고,
      그러려면 클라가 카메라를 움직일 때마다 서버에 알려야 합니다(양방향).
      SSE 로 하면 별도 POST + 세션 ID 매칭을 손으로 재구현해야 합니다.
    · 바이너리 프레임 — JSON→Float32Array 로 줄일 계획인데
      SSE 는 텍스트 전용이라 base64 를 거치고, base64 는 크기가 33% 늘어납니다.
  판단 기준은 "실시간이냐"가 아니라 **"클라가 서버에 계속 말을 거느냐"** 입니다.
════════════════════════════════════════════════════════════

Week 01 에서 미리 계산해둔 것 (로봇 1,000대 기준)
  전 필드 그대로       251.8 KB/회  →  초당 2.46 MB
  필요한 것만·반올림     81.2 KB/회  →  초당 0.79 MB  (68% 절감)

  x: 2.5010755222666936  ← 화면에 픽셀로 그릴 값에 소수점 16자리가 필요한가?
  name, type             ← 매 tick 똑같은데 초당 10번 보내고 있다
                            → 접속하는 순간에만 한 번 보냅니다(manifest)
"""

import asyncio
import json
import logging

from fastapi import WebSocket

from app.state import fleet

log = logging.getLogger(__name__)

# 브로드캐스트 1회가 이 시간을 넘으면 경고.
# tick 주기가 100ms 이므로 그 절반을 넘으면 이미 위험 신호입니다.
SLOW_BROADCAST_MS = 50


def manifest() -> str:
    """접속 순간에 **한 번만** 보내는 정보 — 변하지 않는 것들.

    name 과 type 은 매 tick 똑같습니다. 초당 10번 보낼 이유가 없어요.
    1,000대 기준 이 둘만 빼도 페이로드가 눈에 띄게 줄어듭니다.

    ⚠️ 대신 프론트가 상태를 갖게 됩니다. "id 3번은 R-003 이고 드론"이라는 걸
       클라가 기억해야 해요. 연결이 끊겼다 붙으면 manifest 를 다시 받아야 하고,
       그 사이 로봇이 추가됐다면 모르는 id 가 옵니다.
       → 무상태(매번 다 보냄) vs 대역폭. 우리는 대역폭을 택했습니다.
    """
    return json.dumps({
        "type": "manifest",
        "robots": [
            {"id": r.id, "name": r.name, "kind": r.type}
            for r in fleet.values()
        ],
    })


def snapshot() -> str:
    """매 tick 보내는 것 — 변하는 값만, 반올림해서.

    · round(x, 2) → cm 단위. 화면에 픽셀로 그릴 값에 소수점 16자리는 낭비입니다.
    · battery 는 소수점 1자리면 충분(게이지 표시용)
    · heading 은 정수 도(degree)면 충분 — 0.5도 차이는 화면에서 안 보입니다
    · status 는 StrEnum 이라 json.dumps 가 그냥 문자열로 처리합니다

    💭 왜 dict 를 만들고 json.dumps 를 하나, 처음부터 문자열을 조립하지 않고?
       조립이 더 빠르긴 합니다. 하지만 이스케이프 처리를 직접 하게 되고
       (로봇 이름에 따옴표가 들어가면?) 버그가 조용히 납니다.
       측정해보고 정말 병목이면 그때 바꿉니다 — 지금은 아닙니다.
    """
    return json.dumps({
        "type": "snapshot",
        "robots": [
            {
                "id": r.id,
                "x": round(r.x, 2),
                "y": round(r.y, 2),
                "z": round(r.z, 2),
                "h": round(r.heading),
                "b": round(r.battery, 1),
                "s": r.status,
            }
            for r in fleet.values()
        ],
    })


class ConnectionManager:
    """지금 누가 접속해 있나를 들고 있는 객체."""

    def __init__(self) -> None:
        self.active: list[WebSocket] = []
        self.stats = {
            "connects": 0,
            "disconnects": 0,
            "broadcasts": 0,
            "bytes_sent": 0,
            "last_broadcast_ms": 0.0,
            "max_broadcast_ms": 0.0,
        }

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()               # ← 이걸 해야 통신이 시작됨
        await ws.send_text(manifest())  # 변하지 않는 것은 여기서 한 번만
        self.active.append(ws)
        self.stats["connects"] += 1

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.active:
            self.active.remove(ws)
            self.stats["disconnects"] += 1

    async def broadcast(self, payload: str) -> None:
        """직렬화된 문자열 하나를 전원에게.

        ⚠️ 조심할 것 두 가지

        (1) 직렬화는 호출자가 한 번만 한다
            ❌ for ws in self.active: await ws.send_json(snapshot())
               → 클라마다 81KB 를 새로 만듦. 5명이면 5배 낭비.
            ✅ payload 를 받아서 여러 번 보냄  ← 그래서 이 함수는 str 을 받습니다

        (2) 죽은 소켓 정리 — 단, 순회 중에 리스트를 건드리지 말 것
            브라우저 탭을 닫아도 서버는 바로 모릅니다. 보내려다 에러가 나야 알아요.
            안 치우면 죽은 소켓이 계속 쌓입니다(메모리 누수).
            순회 중에 remove 하면 인덱스가 밀려서 일부를 건너뜁니다.
            → 죽은 것을 모아뒀다가 끝나고 치웁니다.
        """
        dead: list[WebSocket] = []
        sent = 0
        for ws in self.active:
            try:
                await ws.send_text(payload)
                sent += 1
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)
        if dead:
            log.info("죽은 소켓 %d개 정리 (남은 접속 %d)", len(dead), len(self.active))
        self.stats["bytes_sent"] += len(payload) * sent

    async def broadcast_snapshot(self) -> None:
        """시뮬레이터 루프가 매 tick 부르는 진입점."""
        if not self.active:
            # 아무도 안 보는데 81KB 를 만들 이유가 없습니다.
            # 직렬화가 브로드캐스트 비용의 대부분이라 이 한 줄이 꽤 큽니다.
            return

        loop = asyncio.get_running_loop()
        t0 = loop.time()
        await self.broadcast(snapshot())
        elapsed_ms = (loop.time() - t0) * 1000

        self.stats["broadcasts"] += 1
        self.stats["last_broadcast_ms"] = elapsed_ms
        self.stats["max_broadcast_ms"] = max(
            self.stats["max_broadcast_ms"], elapsed_ms
        )
        if elapsed_ms > SLOW_BROADCAST_MS:
            log.warning(
                "브로드캐스트가 느림: %.1fms (접속 %d) — tick 주기 100ms",
                elapsed_ms, len(self.active),
            )

    # ⚠️ 아직 안 다루는 것 — backpressure
    #
    #    위 broadcast 는 **순차** 전송입니다. 느린 클라이언트 하나가 있으면
    #    그 await 에서 루프가 멈춰서 다른 모두가 같이 기다립니다.
    #    그리고 시뮬레이터 tick 도 같이 밀립니다(브로드캐스트를 tick 루프에서 부르므로).
    #
    #    asyncio.gather 로 동시에 보내면 이 문제가 줄지만, 그러면
    #    "느린 클라의 큐가 무한히 자라는" 다른 문제가 생깁니다.
    #    제대로 하려면 클라마다 큐를 두고 밀리면 프레임을 버려야 합니다
    #    (오래된 위치를 굳이 보낼 이유가 없으니 — 이건 배치 저장 때의
    #     "샘플링 vs 버퍼링"과 정확히 같은 구조의 선택입니다).
    #
    #    Week 03 에서 클라를 여러 개 붙여보고 실제로 재본 뒤에 손댑니다.


manager = ConnectionManager()
