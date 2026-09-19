"""Minimal HTTP + WebSocket server for proving the HTTPS tunnel (D guide 5.5)."""

from fastapi import FastAPI, WebSocket

app = FastAPI()


@app.get("/")
def root():
    return {"ok": True, "msg": "HTTP through tunnel works"}


@app.websocket("/ws")
async def ws(sock: WebSocket):
    await sock.accept()
    await sock.send_text("WS through tunnel works")
    async for msg in sock.iter_text():
        await sock.send_text(f"echo: {msg}")
