"""WebSocket 브로드캐스트 — 실시간 텔레메트리를 접속한 클라이언트에게 밀어넣는다.

📌 여기는 혜원님이 채우는 파일입니다.

════════════════════════════════════════════════════════════
이 파일에 만들 것 2개

  ① ConnectionManager   "지금 누가 접속해 있나"를 들고 있는 객체
                        · connect / disconnect / broadcast

  ② snapshot()          fleet 을 전송용 형태로 바꾸는 함수
                        (RobotState 를 그대로 못 보냄 — JSON이 아니니까)

  그리고 main.py 에 WebSocket 엔드포인트를 하나 추가합니다.
════════════════════════════════════════════════════════════

REST와 뭐가 다른가
  REST : 요청이 오면 응답하고 끝. 서버는 아무것도 기억하지 않는다.
  WS   : 연결이 계속 살아 있다. 그래서 "누가 접속 중인지"를 서버가 기억해야 한다.
         이 파일이 존재하는 이유가 그것.

측정해둔 것 (로봇 1,000대 기준, 나중에 이슈에 쓸 숫자)
  전 필드 그대로       251.8 KB/회  →  초당 2.46 MB
  필요한 것만·반올림     81.2 KB/회  →  초당 0.79 MB  (68% 절감)

  x: 2.5010755222666936  ← 화면에 픽셀로 그릴 값에 소수점 16자리가 필요한가?
  name, type             ← 매 tick 똑같은데 초당 10번 보내고 있다

────────────────────────────────────────────────────────────
TODO
  [ ] ① snapshot()
  [ ] ② ConnectionManager
  [ ] ③ main.py 에 @app.websocket("/ws/telemetry") 추가
  [ ] ④ run_simulator 루프에 broadcast 호출 끼워넣기
────────────────────────────────────────────────────────────
"""

import json  # noqa: F401

from fastapi import WebSocket  # noqa: F401

from app.state import fleet  # noqa: F401


# ─────────────────────────────────────────────────────────
# ① snapshot() — fleet 을 전송할 수 있는 형태로
# ─────────────────────────────────────────────────────────
#
#     def snapshot() -> list[dict]:
#         return [{"id": r.id, "x": round(r.x, 2), ...} for r in fleet.values()]
#
# 왜 RobotState 를 그대로 못 보내나:
#   WebSocket 으로는 문자열이나 바이트만 보낼 수 있습니다. 파이썬 객체를
#   JSON 문자열로 바꿔야(직렬화) 하는데, json 모듈은 dataclass 를 모릅니다.
#   그래서 dict 로 풀어줘야 해요.
#
# 무엇을 담을지 (권장):
#   id, x, y, z, heading, battery, status
#   · round(r.x, 2) — 소수점 2자리면 cm 단위입니다. 화면엔 차고 넘쳐요.
#   · name, type 은 뺍니다 — 매 tick 안 변하는 값을 초당 10번 보낼 이유가 없습니다.
#     (접속하는 순간에만 한 번 보내는 방법은 아래 참고)
#   · status 는 StrEnum 이라 그냥 넣어도 JSON 이 됩니다.
#
# 💭 여유되면: 키 이름을 짧게(x→x, heading→h, battery→b) 하면 더 줄어듭니다.
#    다만 프론트에서 읽기 어려워지는 트레이드오프가 있어요. 지금은 긴 이름 권장.


# TODO: snapshot() 정의


# ─────────────────────────────────────────────────────────
# ② ConnectionManager — 접속 중인 클라이언트 목록
# ─────────────────────────────────────────────────────────
#
#     class ConnectionManager:
#         def __init__(self):
#             self.active: list[WebSocket] = []
#
#         async def connect(self, ws: WebSocket) -> None:
#             await ws.accept()          # ← 연결 수락. 이걸 해야 통신이 시작됨
#             self.active.append(ws)
#
#         def disconnect(self, ws: WebSocket) -> None:
#             if ws in self.active:
#                 self.active.remove(ws)
#
#         async def broadcast(self, payload: str) -> None:
#             ...
#
#     manager = ConnectionManager()      # 앱 전체가 공유하는 하나
#
# ⚠️ broadcast 에서 조심할 것 2가지
#
#   (1) 직렬화는 한 번만
#       ❌  for ws in self.active:
#               await ws.send_json(snapshot())   # 클라마다 250KB를 새로 만듦
#       ✅  payload = json.dumps(snapshot())      # 한 번 만들고
#           for ws in self.active:                # 여러 번 보냄
#               await ws.send_text(payload)
#
#   (2) 죽은 소켓 정리 — 단, 순회 중에 리스트를 건드리지 말 것
#       브라우저 탭을 닫아도 서버는 바로 모릅니다. 보내려다 에러가 나야 알아요.
#       안 치우면 죽은 소켓이 계속 쌓입니다(메모리 누수).
#
#       ❌  for ws in self.active:
#               try: await ws.send_text(payload)
#               except Exception: self.active.remove(ws)   # 순회 중 삭제 → 일부 건너뜀
#
#       ✅  dead = []
#           for ws in self.active:
#               try: await ws.send_text(payload)
#               except Exception: dead.append(ws)
#           for ws in dead:
#               self.disconnect(ws)
#
#   💭 아직 안 다루는 것 — backpressure
#      느린 클라이언트 하나가 있으면 그 await 에서 루프가 멈춰서
#      다른 모두가 같이 기다립니다. 이번 주 스코프 밖이지만,
#      "왜 순차 send 가 위험한가"는 이슈에 적어둘 만한 지점입니다.


# TODO: ConnectionManager 정의 + manager 인스턴스


# ─────────────────────────────────────────────────────────
# ③ main.py 에 추가할 엔드포인트 (여기 말고 main.py 에 씁니다)
# ─────────────────────────────────────────────────────────
#
#     from fastapi import WebSocket, WebSocketDisconnect
#     from app.ws import manager
#
#     @app.websocket("/ws/telemetry")
#     async def ws_telemetry(websocket: WebSocket):
#         await manager.connect(websocket)
#         try:
#             while True:
#                 await websocket.receive_text()   # ← 이게 왜 필요한지 아래 설명
#         except WebSocketDisconnect:
#             manager.disconnect(websocket)
#
# 💭 "받을 것도 없는데 왜 receive_text() 로 기다리나?"
#    우리는 서버→클라 한 방향만 쓰는데도 이 루프가 필요합니다.
#    이 함수가 끝나버리면 FastAPI 가 연결을 닫아버리거든요.
#    그리고 클라이언트가 접속을 끊었다는 걸 알아채는 방법이 이것뿐입니다
#    (receive 가 WebSocketDisconnect 를 던져줌).
#
# ─────────────────────────────────────────────────────────
# ④ run_simulator 루프에 끼워넣기 (simulator.py)
# ─────────────────────────────────────────────────────────
#
#     while True:
#         tick()
#         await manager.broadcast(...)     # ← 추가
#         n += 1
#         target = start + n * (TICK_MS / 1000)
#         await asyncio.sleep(max(0, target - loop.time()))
#
#   · tick() 안이 아니라 여기인 이유: tick() 은 동기 함수라 await 를 못 씁니다.
#     그리고 "상태 계산"과 "밖으로 전송"은 관심사가 다릅니다.
#   · 접속자가 0명이면 직렬화 자체를 건너뛰세요. 아무도 안 보는데 250KB를
#     만들 이유가 없습니다.
#   · ⚠️ import 방향 주의: simulator.py 가 ws.py 를 import 하면,
#     ws.py 는 state.py 만 알아야 순환이 안 생깁니다.
