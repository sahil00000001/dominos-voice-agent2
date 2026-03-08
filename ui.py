"""
ui.py — Animated Terminal UI for Domino's Voice Receptionist
=============================================================
Provides two things:

  1. DominosUI  — A full-screen Rich Live dashboard that shows:
       • Domino's branded header
       • Animated status indicator (IDLE / LISTENING / THINKING / SPEAKING)
       • Scrolling conversation transcript
       • Order events log panel (tool call results)
       • Footer with keyboard hint

  2. VoiceUIProcessor — A Pipecat FrameProcessor inserted at the END of the
       pipeline. It observes every frame that flows through the pipeline and
       calls the appropriate DominosUI state-setter, so the display updates
       in real time as the call progresses.

  3. add_log(msg) — Module-level helper so tools.py can push order events
       into the UI's logs panel without importing the whole class.
"""

import threading
from datetime import datetime
from enum import Enum
from typing import List, Optional

from rich import box
from rich.align import Align
from rich.columns import Columns
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

# ── Pipecat imports ────────────────────────────────────────────────────────
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    TextFrame,
    TranscriptionFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


# ── Module-level singleton reference ──────────────────────────────────────
# main.py creates one DominosUI and stores it here so tools.py can call
# add_log() without needing a direct import of the class.
_ui_instance: Optional["DominosUI"] = None


def add_log(message: str) -> None:
    """Push an order-event message into the UI logs panel. Safe to call from
    tools.py or anywhere else — silently does nothing if UI isn't started."""
    if _ui_instance is not None:
        _ui_instance._push_log(message)


# ── Agent state machine ───────────────────────────────────────────────────

class AgentState(Enum):
    IDLE      = "idle"
    LISTENING = "listening"
    THINKING  = "thinking"
    SPEAKING  = "speaking"


# ── State rendering config (spinner style, colors, label) ─────────────────

_STATE_CONFIG = {
    AgentState.IDLE: {
        "spinner":       "dots",
        "spinner_style": "dim white",
        "label":         "  Waiting…  Speak to start your order.",
        "border":        "dim white",
        "title":         "● STATUS",
    },
    AgentState.LISTENING: {
        "spinner":       "arc",
        "spinner_style": "bold green",
        "label":         "  LISTENING  —  I'm all ears! Go ahead…",
        "border":        "bold green",
        "title":         "[bold green]🎤  LISTENING[/bold green]",
    },
    AgentState.THINKING: {
        "spinner":       "dots12",
        "spinner_style": "bold yellow",
        "label":         "  THINKING  —  Priya is working on your order…",
        "border":        "bold yellow",
        "title":         "[bold yellow]🤔  THINKING[/bold yellow]",
    },
    AgentState.SPEAKING: {
        "spinner":       "aesthetic",
        "spinner_style": "bold cyan",
        "label":         "  SPEAKING  —  Priya is talking…",
        "border":        "bold cyan",
        "title":         "[bold cyan]🔊  SPEAKING[/bold cyan]",
    },
}


# ── DominosUI ─────────────────────────────────────────────────────────────

class DominosUI:
    """Full-screen animated terminal dashboard for the voice receptionist."""

    def __init__(self) -> None:
        global _ui_instance
        _ui_instance = self  # register singleton for add_log()

        self._lock        = threading.Lock()
        self._state       = AgentState.IDLE
        self._messages: List[dict]  = []   # {"speaker": str, "text": str, "time": str}
        self._bot_buf     = ""             # accumulates streaming TextFrames
        self._log_lines: List[str] = []    # order event log entries
        self._console     = Console()
        self._live: Optional[Live] = None

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def start(self) -> None:
        self._live = Live(
            self._render(),
            console=self._console,
            refresh_per_second=12,
            screen=True,          # full-screen takeover — no terminal noise
        )
        self._live.start()

    def stop(self) -> None:
        if self._live:
            self._live.stop()

    # ── State setters (called from VoiceUIProcessor) ──────────────────────

    def set_idle(self) -> None:
        with self._lock:
            self._state = AgentState.IDLE
        self._refresh()

    def set_listening(self) -> None:
        with self._lock:
            self._state   = AgentState.LISTENING
            self._bot_buf = ""   # clear any stale partial text
        self._refresh()

    def set_thinking(self) -> None:
        with self._lock:
            self._state = AgentState.THINKING
        self._refresh()

    def set_speaking(self) -> None:
        with self._lock:
            self._state = AgentState.SPEAKING
        self._refresh()

    # ── Conversation helpers ───────────────────────────────────────────────

    def add_user_message(self, text: str) -> None:
        with self._lock:
            self._messages.append({
                "speaker": "You",
                "text":    text,
                "time":    _ts(),
            })
        self._refresh()

    def append_bot_text(self, text: str) -> None:
        """Called for each TextFrame chunk while Priya is generating a reply."""
        with self._lock:
            self._bot_buf += text
        self._refresh()

    def finalise_bot_message(self) -> None:
        """Move the accumulated bot buffer into the permanent message list."""
        with self._lock:
            text = self._bot_buf.strip()
            if text:
                self._messages.append({
                    "speaker": "Priya",
                    "text":    text,
                    "time":    _ts(),
                })
            self._bot_buf = ""
        self._refresh()

    # ── Log panel helper ───────────────────────────────────────────────────

    def _push_log(self, message: str) -> None:
        with self._lock:
            self._log_lines.append(f"[dim]{_ts()}[/dim]  {message}")
            if len(self._log_lines) > 6:
                self._log_lines.pop(0)
        self._refresh()

    # ── Rich rendering ────────────────────────────────────────────────────

    def _refresh(self) -> None:
        if self._live:
            self._live.update(self._render())

    def _render(self) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header",       size=8),
            Layout(name="status",       size=5),
            Layout(name="conversation", ratio=1),
            Layout(name="logs",         size=6),
            Layout(name="footer",       size=3),
        )
        layout["header"].update(self._render_header())
        layout["status"].update(self._render_status())
        layout["conversation"].update(self._render_conversation())
        layout["logs"].update(self._render_logs())
        layout["footer"].update(self._render_footer())
        return layout

    def _render_header(self) -> Panel:
        lines = Text(justify="center")
        lines.append("\n")
        lines.append("🍕  DOMINO'S PIZZA", style="bold red")
        lines.append("   ·   ", style="dim white")
        lines.append("AI Voice Receptionist", style="bold white")
        lines.append("\n\n")
        lines.append("Agent: ", style="dim")
        lines.append("Priya  ", style="bold yellow")
        lines.append("  |  ", style="dim")
        lines.append("STT: Deepgram", style="bold green")
        lines.append("  ·  ", style="dim")
        lines.append("LLM: Gemini 1.5 Flash 8B", style="bold blue")
        lines.append("  ·  ", style="dim")
        lines.append("TTS: Cartesia", style="bold cyan")
        lines.append("\n")
        return Panel(
            Align.center(lines, vertical="middle"),
            border_style="red",
            box=box.DOUBLE_EDGE,
        )

    def _render_status(self) -> Panel:
        cfg = _STATE_CONFIG[self._state]
        spinner = Spinner(
            cfg["spinner"],
            text=cfg["label"],
            style=cfg["spinner_style"],
        )
        return Panel(
            Align.center(spinner, vertical="middle"),
            title=cfg["title"],
            border_style=cfg["border"],
            box=box.ROUNDED,
        )

    def _render_conversation(self) -> Panel:
        table = Table.grid(padding=(0, 2))
        table.add_column(style="dim",       width=9,   no_wrap=True)
        table.add_column(width=7,           no_wrap=True)
        table.add_column(ratio=1)

        messages = self._messages[-14:]  # keep last 14 messages visible

        if not messages and not self._bot_buf:
            placeholder = Text("  Your conversation with Priya will appear here…", style="dim italic")
            table.add_row("", "", placeholder)
        else:
            for msg in messages:
                if msg["speaker"] == "You":
                    speaker = Text("You:", style="bold cyan")
                    txt     = Text(msg["text"], style="white")
                else:
                    speaker = Text("Priya:", style="bold red")
                    txt     = Text(msg["text"], style="italic white")
                table.add_row(Text(msg["time"], style="dim"), speaker, txt)

            # Streaming bot text (shown while Priya is thinking/speaking)
            if self._bot_buf and self._state in (AgentState.THINKING, AgentState.SPEAKING):
                cursor = Text(self._bot_buf.strip() + " ▌", style="italic white")
                table.add_row(
                    Text(_ts(), style="dim"),
                    Text("Priya:", style="bold red"),
                    cursor,
                )

        return Panel(
            table,
            title="[bold white]💬  CONVERSATION[/bold white]",
            border_style="white",
            box=box.ROUNDED,
            padding=(1, 2),
        )

    def _render_logs(self) -> Panel:
        log_text = Text()
        if not self._log_lines:
            log_text.append("  Order events will appear here…", style="dim italic")
        else:
            for line in self._log_lines:
                log_text.append("  ")
                log_text.append_text(Text.from_markup(line))
                log_text.append("\n")
        return Panel(
            log_text,
            title="[bold yellow]📋  ORDER EVENTS[/bold yellow]",
            border_style="yellow",
            box=box.ROUNDED,
        )

    def _render_footer(self) -> Panel:
        txt = Text(justify="center")
        txt.append("Press ", style="dim")
        txt.append("Ctrl+C", style="bold yellow")
        txt.append(" to end the call  ·  Speak clearly into your microphone", style="dim")
        return Panel(txt, border_style="dim", box=box.MINIMAL)


# ── VoiceUIProcessor ──────────────────────────────────────────────────────

class VoiceUIProcessor(FrameProcessor):
    """
    A lightweight Pipecat FrameProcessor that sits at the END of the pipeline
    and observes every downstream frame to drive the DominosUI state machine.

    It passes ALL frames through unchanged — it never blocks or modifies them.
    """

    def __init__(self, ui: DominosUI) -> None:
        super().__init__()
        self._ui = ui

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        # Always pass the frame downstream first so the pipeline is never blocked
        await super().process_frame(frame, direction)

        # ── User speaking state ─────────────────────────────────────────
        if isinstance(frame, UserStartedSpeakingFrame):
            self._ui.set_listening()

        elif isinstance(frame, UserStoppedSpeakingFrame):
            # VAD detected end of user speech; LLM will start soon
            self._ui.set_thinking()

        # ── Transcription (user's words) ────────────────────────────────
        elif isinstance(frame, TranscriptionFrame):
            if frame.text and frame.text.strip():
                self._ui.add_user_message(frame.text.strip())

        # ── LLM generating a response ───────────────────────────────────
        elif isinstance(frame, LLMFullResponseStartFrame):
            self._ui.set_thinking()

        elif isinstance(frame, TextFrame):
            # Streaming text chunks from the LLM
            if frame.text:
                self._ui.append_bot_text(frame.text)

        # ── TTS playing audio ───────────────────────────────────────────
        elif isinstance(frame, TTSStartedFrame):
            self._ui.set_speaking()

        elif isinstance(frame, (TTSStoppedFrame, BotStoppedSpeakingFrame)):
            # TTS finished — commit the bot message and go back to idle
            self._ui.finalise_bot_message()
            self._ui.set_idle()

        await self.push_frame(frame, direction)


# ── Utility ───────────────────────────────────────────────────────────────

def _ts() -> str:
    """Current time as HH:MM:SS string."""
    return datetime.now().strftime("%H:%M:%S")
