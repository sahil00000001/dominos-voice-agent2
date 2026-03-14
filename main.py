"""
============================================================
Domino's Pizza Voice AI Receptionist — Powered by Pipecat
============================================================

HOW TO RUN
----------
1. Copy .env.example to .env and add your three API keys:

       cp .env.example .env          # then open .env and fill in the values

   Your .env should look like this:
       DEEPGRAM_API_KEY=dg_xxxxxxxxxxxxxxxxxxxx
       GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxx
       CARTESIA_API_KEY=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

   Where to get free keys:
       Deepgram  → https://console.deepgram.com/          (free $200 credit)
       Groq      → https://console.groq.com/keys           (free tier, ultra-fast)
       Cartesia  → https://play.cartesia.ai/              (free tier)

2. Create and activate a virtual environment:
       python -m venv venv
       source venv/bin/activate          # Windows: venv\\Scripts\\activate

3. Install dependencies:
       pip install -r requirements.txt

   macOS only — also run:
       brew install portaudio

4. Run the agent:
       python main.py

5. The terminal will go full-screen and show Priya's animated dashboard.
   Speak into your default microphone. Priya will reply through your speakers.
   Press Ctrl+C to end the session.

PIPELINE FLOW
─────────────
Microphone ──► Deepgram STT ──► User Aggregator ──► Groq LLM
       ──► Cartesia TTS ──► Speaker ──► Assistant Aggregator ──► UI Observer
                                  ↕
                        Tool call handlers (tools.py)
                          confirm_order / add_upsell_item / finalise_order
============================================================
"""

import asyncio
import os

from dotenv import load_dotenv

# ── Pipecat core ──────────────────────────────────────────────────────────────
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import BotStartedSpeakingFrame, BotStoppedSpeakingFrame, EndFrame, TTSSpeakFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask

# ── Context / aggregators (universal, provider-agnostic) ─────────────────────
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.turns.user_mute import FunctionCallUserMuteStrategy
from pipecat.turns.user_mute.always_user_mute_strategy import AlwaysUserMuteStrategy

# ── Service integrations ──────────────────────────────────────────────────────
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.groq.llm import GroqLLMService

# ── Local audio transport (microphone + speakers via PyAudio) ─────────────────
from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams

# ── Project modules ───────────────────────────────────────────────────────────
from system_prompt import SYSTEM_PROMPT
from tools import (
    add_upsell_item,
    confirm_order,
    finalise_order,
    get_tool_definitions,
)
from ui import VoiceUIProcessor
from web_ui import WebDominosUI


class DelayedUnmuteStrategy(AlwaysUserMuteStrategy):
    """Keeps the mic muted for `delay_secs` after the bot stops speaking.

    AlwaysUserMuteStrategy unmutes the moment BotStoppedSpeakingFrame arrives,
    but the speaker audio is still physically present in the room for a fraction
    of a second.  Without this delay the microphone picks up the tail-end of
    Priya's voice, Deepgram transcribes it as a user utterance, and the LLM
    fires again — creating an infinite echo loop.
    """

    def __init__(self, delay_secs: float = 0.8):
        super().__init__()
        self._delay_secs = delay_secs
        self._unmute_task = None

    async def process_frame(self, frame) -> bool:
        if isinstance(frame, BotStartedSpeakingFrame):
            if self._unmute_task and not self._unmute_task.done():
                self._unmute_task.cancel()
                self._unmute_task = None
            self._bot_speaking = True
            return True
        elif isinstance(frame, BotStoppedSpeakingFrame):
            if self._unmute_task and not self._unmute_task.done():
                self._unmute_task.cancel()
            self._unmute_task = asyncio.create_task(self._delayed_unmute())
            return True  # stay muted until delay expires
        return self._bot_speaking

    async def _delayed_unmute(self):
        await asyncio.sleep(self._delay_secs)
        self._bot_speaking = False
        self._unmute_task = None


async def main() -> None:

    # ------------------------------------------------------------------
    # 1. Load environment variables from .env
    # ------------------------------------------------------------------
    load_dotenv(override=True)

    deepgram_api_key = os.getenv("DEEPGRAM_API_KEY")
    groq_api_key     = os.getenv("GROQ_API_KEY")
    cartesia_api_key = os.getenv("CARTESIA_API_KEY")

    if not all([deepgram_api_key, groq_api_key, cartesia_api_key]):
        raise EnvironmentError(
            "\n\n  ❌  Missing API keys!\n"
            "  Copy .env.example → .env and fill in all three keys.\n"
            "  See the HOW TO RUN section at the top of this file.\n"
        )

    # ------------------------------------------------------------------
    # 2. Create the terminal UI
    #    DominosUI registers itself as a module singleton so that tools.py
    #    can call add_log() without needing a direct reference.
    # ------------------------------------------------------------------
    ui = WebDominosUI()

    # ------------------------------------------------------------------
    # 3. Local audio transport — mic in, speakers out
    #    Uses your system default audio devices via PyAudio.
    # ------------------------------------------------------------------
    transport = LocalAudioTransport(
        LocalAudioTransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            # VAD is handled by the aggregator below — don't set it here too
        )
    )

    # ------------------------------------------------------------------
    # 4. Deepgram STT — speech → text
    #    Uses Deepgram's nova-2 model (excellent accuracy on phone speech).
    # ------------------------------------------------------------------
    stt = DeepgramSTTService(api_key=deepgram_api_key)

    # ------------------------------------------------------------------
    # 5. Cartesia TTS — text → speech
    #    Voice "71a7ad14-091c-4e8e-a314-022ece01c121" is a warm, natural
    #    female English voice that suits a receptionist persona perfectly.
    #    Browse all voices at: https://play.cartesia.ai/
    # ------------------------------------------------------------------
    tts = CartesiaTTSService(
        api_key=cartesia_api_key,
        voice_id="71a7ad14-091c-4e8e-a314-022ece01c121",
    )

    # ------------------------------------------------------------------
    # 6. Groq LLM — the brain of the agent
    #    llama-3.3-70b-versatile is ultra-fast on Groq's free tier and
    #    has excellent function-calling / tool-use support.
    # ------------------------------------------------------------------
    llm = GroqLLMService(
        api_key=groq_api_key,
        model="llama-3.3-70b-versatile",
    )

    # ------------------------------------------------------------------
    # 7. Register tool call handlers
    #    When Groq emits a function call, Pipecat intercepts it, runs
    #    the matching Python function, and injects the result back into
    #    the conversation context so the LLM can continue naturally.
    # ------------------------------------------------------------------
    llm.register_function("confirm_order",   confirm_order)
    llm.register_function("add_upsell_item", add_upsell_item)
    llm.register_function("finalise_order",  finalise_order)

    # While a tool is executing, speak a filler so there's no dead silence
    @llm.event_handler("on_function_calls_started")
    async def on_tool_started(service, function_calls):
        await tts.queue_frame(TTSSpeakFrame("One moment please."))


    # ------------------------------------------------------------------
    # 8. Build the LLM context with system prompt + tool definitions
    #    Groq uses OpenAI-compatible format — system prompt goes as a
    #    messages entry, not a service-level parameter.
    # ------------------------------------------------------------------
    context = LLMContext(
        messages=[{"role": "system", "content": SYSTEM_PROMPT}],
        tools=get_tool_definitions(),
    )

    # user_aggregator  — collects STT transcripts → adds to context as user msg
    # assistant_aggregator — collects LLM output → adds to context as asst msg
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            # vad_stop_secs: wait 0.8s of silence before treating speech as done
            # This prevents cutting off mid-sentence
            vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.8)),
            # Mute user input while bot is speaking or a tool is running.
            # AlwaysUserMuteStrategy suppresses ALL mic audio and transcriptions
            # while the bot speaks, preventing echo feedback from being sent to
            # the LLM as fake "user" messages.
            user_mute_strategies=[
                DelayedUnmuteStrategy(delay_secs=0.8),
                FunctionCallUserMuteStrategy(),
            ],
        ),
    )

    # LLMFullResponseEndFrame is consumed internally by LLMAssistantAggregator
    # and never reaches VoiceUIProcessor downstream. Use this event handler
    # instead to capture the full bot response text for the UI.
    @assistant_aggregator.event_handler("on_assistant_turn_stopped")
    async def on_bot_message(agg, message):
        ui.append_bot_text(message.content)

    # ------------------------------------------------------------------
    # 9. UI observer processor
    #    Placed at the END of the pipeline so it can see every frame that
    #    flows through: VAD events, transcriptions, LLM text, TTS events.
    #    It never blocks or modifies frames — just observes.
    # ------------------------------------------------------------------
    ui_observer = VoiceUIProcessor(ui, context=context)

    # ------------------------------------------------------------------
    # 10. Assemble the pipeline
    #
    #   transport.input()   → raw mic audio frames
    #   stt                 → TranscriptionFrame (user's words)
    #   user_aggregator     → accumulates transcript into LLMContext
    #   llm                 → TextFrame stream (Priya's reply)
    #   tts                 → audio frames (speech synthesis)
    #   transport.output()  → plays audio through speakers
    #   assistant_aggregator→ stores reply in LLMContext (conversation memory)
    #   ui_observer         → observes ALL frames, drives the live dashboard
    # ------------------------------------------------------------------
    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            user_aggregator,
            llm,
            tts,
            transport.output(),
            assistant_aggregator,
            ui_observer,        # ← UI sits at the end, sees everything
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            enable_metrics=False,
            # Prevent Priya from being interrupted mid-sentence by her own
            # voice echoing back through the microphone
            allow_interruptions=False,
        ),
    )

    # ------------------------------------------------------------------
    # 11. End-call hook: once finalise_order completes, shut the pipeline
    #     down gracefully after allowing enough time for the closing TTS
    #     to finish playing (3 seconds).
    # ------------------------------------------------------------------
    async def _finalise_and_end(params) -> None:
        await finalise_order(params)
        await asyncio.sleep(3.0)
        await task.queue_frames([EndFrame()])

    llm.register_function("finalise_order", _finalise_and_end)

    # ------------------------------------------------------------------
    # 12. Speak the opening greeting directly via TTS.
    #     The first real LLM call fires only
    #     after the user speaks and provides actual content.
    # ------------------------------------------------------------------
    GREETING = "Hi, thank you for calling Domino's! I'm Priya. May I know your name please?"
    await task.queue_frames([TTSSpeakFrame(GREETING)])

    # ------------------------------------------------------------------
    # 12. Start the UI and run the pipeline
    #     ui.start() switches the terminal to the full-screen dashboard.
    #     runner.run() blocks until the pipeline stops or Ctrl+C is pressed.
    #     ui.stop() restores the terminal in all cases.
    # ------------------------------------------------------------------
    runner = PipelineRunner(handle_sigint=True)

    ui.start()
    # Show the opening greeting in the chat panel
    ui.append_bot_text(GREETING)
    ui.finalise_bot_message()
    try:
        await runner.run(task)
    finally:
        ui.stop()
        print("\n  📞  Call ended. Thank you for using Domino's Voice Receptionist!\n")


if __name__ == "__main__":
    asyncio.run(main())
