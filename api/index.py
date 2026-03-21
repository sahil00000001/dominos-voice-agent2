"""
api/index.py — Domino's Voice Agent · Vercel FastAPI Entrypoint
===============================================================
Single FastAPI app detected by Vercel as the Python serverless entrypoint.
Exposes three endpoints consumed by the browser voice pipeline:

  POST /api/transcribe  — audio bytes  → Deepgram STT  → transcript JSON
  POST /api/chat        — message JSON → Groq LLM       → reply + tool events
  POST /api/tts         — text JSON    → Cartesia TTS   → MP3 audio bytes

All external API calls use stdlib urllib (no extra deps beyond fastapi).
Conversation history is owned by the browser and sent with every /api/chat
request because Vercel serverless functions are stateless between calls.
"""

import json
import os
import pathlib
import urllib.error
import urllib.parse
import urllib.request

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response

# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(title="Domino's Voice Agent API")

# Allow the browser (same Vercel domain or localhost in dev) to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "OPTIONS", "GET"],
    allow_headers=["*"],
)

# ── Frontend ───────────────────────────────────────────────────────────────────

# api/static/ is a subdirectory of api/ — guaranteed to be bundled by Vercel
# (Vercel's Python runtime only includes the entrypoint directory and its children)
_STATIC_DIR = pathlib.Path(__file__).parent / "static"

@app.get("/")
async def serve_index():
    """
    Serve the browser voice UI at the root URL.
    The HTML lives in api/static/index.html so it's always inside Vercel's
    serverless function bundle. public/index.html is kept for local reference.
    """
    return HTMLResponse((_STATIC_DIR / "index.html").read_text(encoding="utf-8"))


@app.get("/favicon.ico")
async def favicon():
    """Return empty 204 so browsers stop logging 404 for favicon."""
    return Response(status_code=204)


@app.get("/api/debug")
async def debug():
    """
    Returns which API keys are present (masked) so you can verify Vercel
    environment variables are configured correctly. Remove before production.
    """
    def mask(val: str | None) -> str:
        if not val:
            return "NOT SET ❌"
        return val[:6] + "…" + val[-4:] + " ✅"

    return JSONResponse({
        "DEEPGRAM_API_KEY": mask(os.environ.get("DEEPGRAM_API_KEY")),
        "GROQ_API_KEY":     mask(os.environ.get("GROQ_API_KEY")),
        "CARTESIA_API_KEY": mask(os.environ.get("CARTESIA_API_KEY")),
    })

# ── System prompt ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are Priya, a friendly voice receptionist for Domino's Pizza India. You handle incoming calls to take orders, confirm delivery details, and offer deals. This is a voice call — keep all responses SHORT, natural, and conversational. Never use bullet points, lists, or formatting.

━━━━━━━━━━━━━━━━━━━━━━━━
CRITICAL SPEAKING RULES  (follow these above everything else)
━━━━━━━━━━━━━━━━━━━━━━━━

- ONE question per turn. Ask it. Then STOP. Wait for the customer to answer before you speak again.
- Maximum 2 sentences per response. Never speak more than 25 words at a time.
- Never ask two things in one message (e.g. don't ask veg/non-veg AND size together).
- Never repeat yourself. If you already said something, do not say it again.
- After the closing line in Step 6, say ABSOLUTELY NOTHING MORE. Go completely silent. The call ends automatically.

━━━━━━━━━━━━━━━━━━━━━━━━
MENU  (the ONLY items you may offer or price)
━━━━━━━━━━━━━━━━━━━━━━━━

VEGETARIAN PIZZAS
- Margherita           (Regular ₹199 / Medium ₹299 / Large ₹499)
- Farmhouse            (Regular ₹249 / Medium ₹349 / Large ₹549)
- Veggie Paradise      (Regular ₹249 / Medium ₹349 / Large ₹549)
- Paneer Makhani       (Regular ₹279 / Medium ₹379 / Large ₹599)
- Double Cheese Margherita (Regular ₹229 / Medium ₹329 / Large ₹529)

NON-VEGETARIAN PIZZAS
- Chicken Dominator    (Regular ₹299 / Medium ₹399 / Large ₹649)
- Pepper Barbeque Chicken (Regular ₹279 / Medium ₹379 / Large ₹599)
- Chicken Golden Delight (Regular ₹269 / Medium ₹369 / Large ₹579)
- Keema Do Pyaza       (Regular ₹299 / Medium ₹399 / Large ₹649)

SIDES & DRINKS  (for upsell only)
- Garlic Bread         ₹79
- Choco Lava Cake      ₹49
- Pepsi (330ml)        ₹30

━━━━━━━━━━━━━━━━━━━━━━━━
CALL FLOW  (follow this EXACTLY, one step at a time)
━━━━━━━━━━━━━━━━━━━━━━━━

STEP 1 — Greet. Ask ONLY the name. Stop.
Say: "Hi, thank you for calling Domino's! I'm Priya. May I know your name please?"
Wait for name. Do not say anything else until customer gives their name.

STEP 2 — Take the order. ONE question at a time. Stop after each question and wait.
  2a. Ask ONLY: veg or non-veg?
  2b. (After answer) Ask ONLY: which pizza from the menu?
  2c. (After answer) Ask ONLY: what size — regular, medium, or large?

STEP 3 — Ask for delivery address. Stop and wait.
Say something like: "Great! What's your delivery address, [name]?"

STEP 4 — Read back order ONCE to confirm. Stop and wait for YES.
Example: "So that's one Large Double Cheese Margherita to [address] — is that right?"
When customer confirms, call confirm_order tool immediately.

STEP 5 — Offer exactly ONE upsell (one short sentence). Stop and wait.
  • Order total > ₹400 → "Would you like to add a Choco Lava Cake for just ₹49?"
  • Pizza only, no sides → "Can I add a Garlic Bread for ₹79?"
  • Default → "How about a Pepsi for ₹30?"
If accepted call add_upsell_item tool. If declined, move to Step 6 immediately.

STEP 6 — Say ONLY this closing line, nothing more:
"Perfect [name]! Your order is confirmed and will be delivered in about 30 to 45 minutes. Thank you for calling Domino's, have a great day!"
Then call finalise_order tool immediately. After that, say NOTHING. Stay completely silent.

━━━━━━━━━━━━━━━━━━━━━━━━
STRICT RULES
━━━━━━━━━━━━━━━━━━━━━━━━

- Short sentences only. This is a phone call.
- Use the customer's name naturally at least once per step.
- NEVER repeat or summarise the order after confirm_order has been called.
- NEVER repeat or summarise the order after add_upsell_item has been called.
- NEVER say the order total or delivery estimate more than once.
- NEVER add extra commentary, filler, or summaries between steps.
- NEVER make up menu items or prices not listed above.
- NEVER say "one moment please" more than once in the call.
- If asked about complaints or store hours: "For that I'd need to transfer you to our team — but let me finish your order first!"
"""

# ── Tool definitions (OpenAI / Groq compatible) ───────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "confirm_order",
            "description": (
                "Call once the customer has verbally confirmed their full order and address. "
                "Pass all order details and the calculated total."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_name":    {"type": "string", "description": "Customer's first name."},
                    "order_items":      {"type": "array",  "items": {"type": "string"}, "description": "e.g. ['1x Farmhouse Pizza (Medium)']"},
                    "delivery_address": {"type": "string", "description": "Full delivery address as spoken."},
                    "order_total_inr":  {"type": "number", "description": "Order total in Indian Rupees."},
                },
                "required": ["customer_name", "order_items", "delivery_address", "order_total_inr"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_upsell_item",
            "description": "Call when the customer agrees to an upsell offer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_name":      {"type": "string", "description": "e.g. 'Choco Lava Cake'"},
                    "item_price_inr": {"type": "number", "description": "Price in Indian Rupees."},
                },
                "required": ["item_name", "item_price_inr"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finalise_order",
            "description": "Call at the very end of the call after thanking the customer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_name":              {"type": "string",  "description": "Customer's first name."},
                    "final_order_summary":        {"type": "string",  "description": "Full human-readable order summary."},
                    "estimated_delivery_minutes": {"type": "integer", "description": "Delivery ETA in minutes (default 35)."},
                },
                "required": ["customer_name", "final_order_summary"],
            },
        },
    },
]

# ── Tool execution logic ───────────────────────────────────────────────────────

def execute_tool(name: str, args: dict) -> tuple[str, dict | None]:
    """
    Run a tool call server-side and return:
      - result_str : fed back to Groq as the tool's return value
      - event_dict : sent to the browser to update the order events panel
    """
    if name == "confirm_order":
        customer = args.get("customer_name", "Customer")
        items    = args.get("order_items", [])
        address  = args.get("delivery_address", "")
        total    = float(args.get("order_total_inr", 0))
        return (
            f"Order logged. Total: ₹{total:.2f}. "
            "DO NOT repeat or summarise the order. Ask ONE upsell now.",
            {"type": "confirmed", "customer": customer, "items": items, "address": address, "total": total},
        )

    elif name == "add_upsell_item":
        item  = args.get("item_name", "item")
        price = float(args.get("item_price_inr", 0))
        return (
            f"{item} added. DO NOT repeat order. "
            "Say ONLY the closing line then call finalise_order immediately.",
            {"type": "upsell", "item": item, "price": price},
        )

    elif name == "finalise_order":
        customer = args.get("customer_name", "Customer")
        summary  = args.get("final_order_summary", "")
        eta      = int(args.get("estimated_delivery_minutes", 35))
        return (
            "Order finalised. Call complete. Say nothing more.",
            {"type": "finalised", "customer": customer, "summary": summary, "eta": eta},
        )

    return ("OK", None)

# ── Groq helper ───────────────────────────────────────────────────────────────

def _groq_call(messages: list, use_tools: bool) -> dict:
    """
    Make a synchronous (non-streaming) call to Groq's OpenAI-compatible API.
    Uses stdlib urllib so no extra packages are needed.
    """
    groq_key = os.environ.get("GROQ_API_KEY", "")
    payload: dict = {
        "model": "llama-3.3-70b-versatile",
        "messages": messages,
        "max_tokens": 200,
        "stream": False,
    }
    if use_tools:
        payload["tools"]       = TOOLS
        payload["tool_choice"] = "auto"

    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={
            "Authorization": f"Bearer {groq_key}",
            "Content-Type":  "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read())


# ══════════════════════════════════════════════════════════════════════════════
# ENDPOINT 1 — STT: audio → transcript
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/api/transcribe")
async def transcribe(request: Request):
    """
    Receives raw audio bytes (webm/ogg/wav) from MediaRecorder in the browser.
    Forwards to Deepgram's prerecorded transcription REST endpoint and returns
    the transcript as JSON: { "transcript": "..." }
    """
    audio_data   = await request.body()
    content_type = request.headers.get("content-type", "audio/webm")
    deepgram_key = os.environ.get("DEEPGRAM_API_KEY", "")

    params = urllib.parse.urlencode({
        "model":        "nova-2",
        "smart_format": "true",
        "language":     "en-IN",
        "punctuate":    "true",
    })
    url = f"https://api.deepgram.com/v1/listen?{params}"

    try:
        req = urllib.request.Request(
            url,
            data=audio_data,
            headers={
                "Authorization": f"Token {deepgram_key}",
                "Content-Type":  content_type,
            },
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read())

        transcript = (
            result
            .get("results", {})
            .get("channels", [{}])[0]
            .get("alternatives", [{}])[0]
            .get("transcript", "")
        )
        return JSONResponse({"transcript": transcript})

    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        return JSONResponse({"error": f"Deepgram {exc.code}: {detail}", "transcript": ""}, status_code=502)
    except Exception as exc:
        return JSONResponse({"error": str(exc), "transcript": ""}, status_code=500)


# ══════════════════════════════════════════════════════════════════════════════
# ENDPOINT 2 — LLM: transcript + history → reply + tool events
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/api/chat")
async def chat(request: Request):
    """
    Receives the full conversation history from the browser (stateless backend).
    Runs an agentic loop: calls Groq → executes any tool calls server-side →
    calls Groq again with tool results → repeats until no more tool_calls.

    Returns:
      {
        "text":        str,          # assistant reply to speak/display
        "tool_events": list[dict],   # order events for the browser UI panel
        "messages":    list[dict],   # updated history for browser to store
        "call_ended":  bool          # true when finalise_order was called
      }
    """
    body             = await request.json()
    client_messages  = body.get("messages", [])

    # Prepend system prompt — never stored on the client
    all_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + client_messages

    tool_events: list = []
    call_ended        = False
    reply_text        = ""
    last_msg          = {}

    try:
        # Agentic loop — Groq may chain multiple tool calls in one turn
        for _ in range(6):
            result   = _groq_call(all_messages, use_tools=True)
            last_msg = result["choices"][0]["message"]
            all_messages.append(last_msg)

            if not last_msg.get("tool_calls"):
                # No more tool calls — this is the final assistant reply
                reply_text = last_msg.get("content") or ""
                break

            # Execute every tool call Groq requested
            for tc in last_msg["tool_calls"]:
                name = tc["function"]["name"]
                args = json.loads(tc["function"]["arguments"])

                tool_result, event = execute_tool(name, args)
                if event:
                    tool_events.append(event)
                    if event["type"] == "finalised":
                        call_ended = True   # signal browser to end session

                # Feed the tool result back so Groq can continue
                all_messages.append({
                    "role":         "tool",
                    "tool_call_id": tc["id"],
                    "content":      tool_result,
                })

        # Strip system message before returning — client only needs user/assistant/tool messages
        updated_history = [m for m in all_messages if m.get("role") != "system"]

        return JSONResponse({
            "text":       reply_text,
            "tool_events": tool_events,
            "messages":   updated_history,
            "call_ended": call_ended,
        })

    except urllib.error.HTTPError as exc:
        # Surface the full Groq error body so it's visible in browser DevTools
        detail = exc.read().decode(errors="replace")
        groq_key_set = bool(os.environ.get("GROQ_API_KEY"))
        return JSONResponse({
            "error": f"Groq HTTP {exc.code}: {detail}",
            "hint": "GROQ_API_KEY is set" if groq_key_set else "GROQ_API_KEY is NOT SET in Vercel env vars",
            "text": "", "tool_events": [], "messages": client_messages, "call_ended": False,
        }, status_code=502)
    except Exception as exc:
        import traceback
        return JSONResponse({
            "error": str(exc),
            "trace": traceback.format_exc(),
            "text": "", "tool_events": [], "messages": client_messages, "call_ended": False,
        }, status_code=500)


# ══════════════════════════════════════════════════════════════════════════════
# ENDPOINT 3 — TTS: text → MP3 audio
# ══════════════════════════════════════════════════════════════════════════════

# Cartesia voice: warm natural female English, used for Priya's persona
_VOICE_ID = "71a7ad14-091c-4e8e-a314-022ece01c121"
_MODEL_ID  = "sonic-2024-10-19"

@app.post("/api/tts")
async def tts(request: Request):
    """
    Receives { "text": "..." } and calls Cartesia's REST /tts/bytes endpoint.
    Returns raw MP3 bytes which the browser decodes with AudioContext.decodeAudioData().
    MP3 is preferred over WAV because it's ~10x smaller, reducing latency.
    """
    body         = await request.json()
    text         = body.get("text", "").strip()
    cartesia_key = os.environ.get("CARTESIA_API_KEY", "")

    if not text:
        return JSONResponse({"error": "No text provided"}, status_code=400)

    payload = {
        "transcript": text,
        "model_id":   _MODEL_ID,
        "voice":      {"mode": "id", "id": _VOICE_ID},
        "output_format": {
            "container":  "mp3",
            "bit_rate":   128000,
            "sample_rate": 44100,
        },
        "language": "en",
    }

    try:
        req = urllib.request.Request(
            "https://api.cartesia.ai/tts/bytes",
            data=json.dumps(payload).encode(),
            headers={
                "X-API-Key":        cartesia_key,
                "Cartesia-Version": "2024-06-10",
                "Content-Type":     "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            audio_bytes = resp.read()

        return Response(content=audio_bytes, media_type="audio/mpeg")

    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        return JSONResponse({"error": f"Cartesia {exc.code}: {detail}"}, status_code=502)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)
