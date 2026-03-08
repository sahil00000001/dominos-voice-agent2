"""
web_ui.py — Web Dashboard for Domino's Voice Receptionist
==========================================================
Replaces the terminal Rich UI with a beautiful browser dashboard served over
FastAPI + WebSocket. Keeps the exact same interface as DominosUI so that
VoiceUIProcessor and tools.py work without any modification.
"""

import asyncio
import json
import os
import re
import threading
import time
import webbrowser
from datetime import datetime
from typing import Optional, Set

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

# ── Module-level singleton (mirrors ui.py pattern so tools.py works) ──────────
_ui_instance: Optional["WebDominosUI"] = None


def add_log(message: str) -> None:
    """Called from tools.py — forwards to the web dashboard."""
    if _ui_instance is not None:
        _ui_instance._push_log(message)


class WebDominosUI:
    """
    Web-based replacement for DominosUI.
    Starts a FastAPI/uvicorn server in a background daemon thread and
    broadcasts real-time JSON events to all connected browser clients.
    """

    def __init__(self, port: int = 8000) -> None:
        global _ui_instance
        _ui_instance = self

        # Also patch ui.py's singleton so `from ui import add_log` still works
        import ui as _ui_mod
        _ui_mod._ui_instance = self  # type: ignore[attr-defined]

        self._port = port
        self._connections: Set[WebSocket] = set()
        self._server_loop: Optional[asyncio.AbstractEventLoop] = None
        self._current_state = "idle"
        self._stats = {"calls": 0, "orders": 0, "revenue": 0.0, "upsells": 0}
        self._app = self._build_app()

    # ── FastAPI app ───────────────────────────────────────────────────────────

    def _build_app(self) -> FastAPI:
        app = FastAPI()

        @app.get("/")
        async def dashboard():
            html_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
            with open(html_path, encoding="utf-8") as f:
                return HTMLResponse(f.read())

        @app.websocket("/ws")
        async def ws_endpoint(websocket: WebSocket):
            await websocket.accept()
            self._connections.add(websocket)
            # Send current state to newly connected client
            try:
                await websocket.send_text(json.dumps({
                    "type": "init",
                    "state": self._current_state,
                    "stats": self._stats,
                }))
            except Exception:
                pass
            try:
                while True:
                    await websocket.receive_text()
            except WebSocketDisconnect:
                self._connections.discard(websocket)

        return app

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        def _run():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._server_loop = loop
            config = uvicorn.Config(
                self._app, host="0.0.0.0", port=self._port, log_level="error"
            )
            server = uvicorn.Server(config)
            loop.run_until_complete(server.serve())

        t = threading.Thread(target=_run, daemon=True)
        t.start()

        # Wait for server to bind before opening browser
        time.sleep(1.2)
        url = f"http://localhost:{self._port}"
        print(f"\n  🌐  Dashboard → {url}\n  Speak into your mic. Press Ctrl+C to end.\n")
        webbrowser.open(url)

    def stop(self) -> None:
        pass  # daemon thread exits automatically with the process

    # ── State setters (identical interface to DominosUI) ──────────────────────

    def set_idle(self) -> None:
        self._current_state = "idle"
        self._emit({"type": "state", "state": "idle"})

    def set_listening(self) -> None:
        self._current_state = "listening"
        self._emit({"type": "state", "state": "listening"})

    def set_thinking(self) -> None:
        self._current_state = "thinking"
        self._emit({"type": "state", "state": "thinking"})

    def set_speaking(self) -> None:
        self._current_state = "speaking"
        self._emit({"type": "state", "state": "speaking"})

    # ── Conversation helpers (identical interface to DominosUI) ───────────────

    def add_user_message(self, text: str) -> None:
        self._emit({"type": "user_msg", "text": text, "time": _ts()})

    def append_bot_text(self, text: str) -> None:
        self._emit({"type": "bot_chunk", "text": text})

    def finalise_bot_message(self) -> None:
        self._emit({"type": "bot_done", "time": _ts()})

    # ── Order log ─────────────────────────────────────────────────────────────

    def _push_log(self, message: str) -> None:
        # Strip Rich markup tags like [bold green], [/dim], etc.
        clean = re.sub(r"\[/?[^\]]*\]", "", message).strip()

        # Detect event type and update stats
        event_type = "default"
        if "ORDER CONFIRMED" in message:
            event_type = "confirmed"
            self._stats["orders"] += 1
            m = re.search(r"₹(\d+(?:\.\d+)?)", clean)
            if m:
                self._stats["revenue"] += float(m.group(1))
        elif "UPSELL ADDED" in message:
            event_type = "upsell"
            self._stats["upsells"] += 1
            m = re.search(r"₹(\d+(?:\.\d+)?)", clean)
            if m:
                self._stats["revenue"] += float(m.group(1))
        elif "ORDER FINALISED" in message:
            event_type = "finalised"

        self._emit({
            "type": "order_event",
            "message": clean,
            "event_type": event_type,
            "time": _ts(),
            "stats": {**self._stats},
        })

    # ── Broadcast ─────────────────────────────────────────────────────────────

    def _emit(self, event: dict) -> None:
        if not self._connections or self._server_loop is None:
            return
        data = json.dumps(event, ensure_ascii=False)

        async def _send():
            dead: Set[WebSocket] = set()
            for ws in list(self._connections):
                try:
                    await ws.send_text(data)
                except Exception:
                    dead.add(ws)
            self._connections -= dead

        asyncio.run_coroutine_threadsafe(_send(), self._server_loop)


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")
