# 🍕 Domino's Pizza Voice AI Receptionist

A fully working, real-time voice AI agent that acts as a phone receptionist for Domino's Pizza. You speak into your microphone, it listens, understands, and replies through your speakers — just like talking to a real person on a phone call.

---

## What It Does

When you run the program, an AI agent named **Priya** answers the call and:

1. Greets you and asks for your name
2. Takes your pizza order
3. Asks for your delivery address
4. Repeats the full order back to confirm
5. Offers one upsell deal (Garlic Bread, Choco Lava Cake, Pepsi, etc.)
6. Gives a 30–45 minute delivery estimate and ends the call

All of this happens through **real voice** — you speak, it listens, it talks back.

---

## Tech Stack

| Layer | Service | Why |
|---|---|---|
| **Speech-to-Text** | Deepgram | Fast, accurate, free tier available |
| **AI Brain** | Google Gemini 2.5 Flash | Smart, fast, free API tier |
| **Text-to-Speech** | Cartesia | Natural warm voice, low latency, free tier |
| **Framework** | Pipecat | Connects all the above into a real-time voice pipeline |
| **Terminal UI** | Rich | Beautiful animated full-screen dashboard |

---

## Project Structure

```
dominos-voice-agent/
├── main.py           ← Starts everything, builds the pipeline
├── tools.py          ← Order functions Gemini can call (confirm, upsell, finalise)
├── system_prompt.py  ← Priya's personality and call script
├── ui.py             ← Animated terminal dashboard
├── requirements.txt  ← All Python dependencies
├── .env.example      ← Template for API keys
└── .env              ← Your actual API keys (never share this file)
```

---

## How It Works — The Pipeline

```
Your Microphone
      ↓
Deepgram STT  ← converts your speech to text in real time
      ↓
User Aggregator  ← collects your words, waits for a pause
      ↓
Gemini 2.5 Flash LLM  ← thinks and generates Priya's reply
      ↓  (may call tools: confirm_order / add_upsell_item / finalise_order)
Cartesia TTS  ← converts Priya's reply text to natural speech audio
      ↓
Your Speakers
      ↓
Assistant Aggregator  ← remembers what was said (conversation memory)
      ↓
UI Observer  ← updates the live dashboard display
```

Every component is connected by **Pipecat**, which manages the real-time audio streaming between all services.

---

## The Three AI Tools (Function Calling)

Gemini can call these Python functions mid-conversation when appropriate:

### `confirm_order`
Called when the customer confirms their full order.
- Logs: customer name, items ordered, delivery address, total price
- Tells Gemini: "Order confirmed, proceed to upsell"

### `add_upsell_item`
Called when the customer accepts an upsell offer.
- Logs: item name and price
- Tells Gemini: "Item added, give delivery estimate"

### `finalise_order`
Called at the very end of the call.
- Logs: final order summary and estimated delivery time
- Tells Gemini: "Call complete"

These appear in the **ORDER EVENTS** panel on the dashboard in real time.

---

## The Terminal UI

When running, the terminal goes full-screen and shows:

```
╔══════════════════════════════════════════════════════════╗
║  🍕  DOMINO'S PIZZA  ·  AI Voice Receptionist           ║
║  Agent: Priya  |  Deepgram · Gemini 2.5 Flash · Cartesia║
╠══════════════════════════════════════════════════════════╣
║  🎤  LISTENING                                           ║
║     ⠙  LISTENING — I'm all ears! Go ahead…              ║
╠══════════════════════════════════════════════════════════╣
║  💬  CONVERSATION                                        ║
║  14:02:10  You:    I want a large Farmhouse pizza        ║
║  14:02:13  Priya:  Sure! And your delivery address?      ║
╠══════════════════════════════════════════════════════════╣
║  📋  ORDER EVENTS                                        ║
║  14:02:25  ✔ ORDER CONFIRMED  Raj · ₹349                 ║
╚══════════════════════════════════════════════════════════╝
```

**Status animations:**
- 🎤 **Green arc spinner** = Listening (you are talking)
- 🤔 **Yellow dots spinner** = Thinking (Gemini is processing)
- 🔊 **Cyan wave spinner** = Speaking (Priya is talking)
- ⚪ **Dim dots** = Idle (waiting for you to speak)

---

## Setup (First Time)

### Step 1 — Get Free API Keys

| Service | Link | Notes |
|---|---|---|
| Deepgram | https://console.deepgram.com | Sign up → copy API Key |
| Gemini | https://aistudio.google.com/app/apikey | Click "Create API key" |
| Cartesia | https://play.cartesia.ai | Sign up → Settings → API Keys |

### Step 2 — Install Python 3.12

Download from: https://python.org/downloads/release/python-3120
**Important:** Check "Add Python to PATH" during install.

### Step 3 — Set Up the Project

```powershell
cd "C:\Users\vashi\Downloads\Ai-Agent\dominos-voice-agent"
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

### Step 4 — Add Your API Keys

```powershell
copy .env.example .env
notepad .env
```

Fill in your three keys:
```
DEEPGRAM_API_KEY=dg_xxxxxxxxxxxxxxxxxxxx
GEMINI_API_KEY=AIzaxxxxxxxxxxxxxxxxxxxxxxxx
CARTESIA_API_KEY=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

---

## Running the Agent

```powershell
cd "C:\Users\vashi\Downloads\Ai-Agent\dominos-voice-agent"
venv\Scripts\activate
python main.py
```

Press **Ctrl+C** to end the call.

> **Tip:** Use headphones for the best experience. Without headphones, the microphone can pick up Priya's voice from the speakers and cause echo. Headphones completely prevent this.

---

## Every Time You Come Back

You only need to activate the venv and run:

```powershell
cd "C:\Users\vashi\Downloads\Ai-Agent\dominos-voice-agent"
venv\Scripts\activate
python main.py
```

---

## Errors We Fixed During Setup

| Error | Cause | Fix |
|---|---|---|
| `Python 3.14` numba build failure | Pipecat needs Python ≤ 3.13 | Installed Python 3.12 specifically |
| `FrameDirection` import error | Moved to `frame_processor` module in this version | Changed import path |
| `CartesiaTTSService voice_id` error | API changed from `settings=` to direct `voice_id=` | Passed `voice_id` directly |
| `GoogleLLMSettings system_instruction` error | Parameter moved to `GoogleLLMService` directly | Passed `system_instruction` to the service |
| `'dict' object has no attribute 'confidence'` | VAD params need `VADParams` object, not a plain dict | Used `VADParams(stop_secs=0.8)` |
| Echo / repeated words | Duplicate VAD in both transport and aggregator | Removed VAD from transport, kept only in aggregator |

---

## Customisation Ideas

- **Change Priya's voice** — Browse voices at https://play.cartesia.ai and replace the `voice_id` in `main.py`
- **Change the menu** — Edit `system_prompt.py` to add/remove items and prices
- **Change the personality** — Edit the system prompt to make Priya more formal, more casual, etc.
- **Add more tools** — Add functions in `tools.py` and register them in `main.py` (e.g. `check_order_status`, `apply_coupon`)
- **Connect to a real POS** — Replace the `print` logs in `tools.py` with actual API calls to your ordering system

---

## Dependencies

```
pipecat-ai[google,deepgram,cartesia,local]  ← core framework + all services
torch (CPU)                                  ← powers the Silero VAD model
python-dotenv                                ← loads API keys from .env file
rich                                         ← beautiful terminal UI
```

---

*Built with Pipecat · Gemini 2.5 Flash · Deepgram · Cartesia*
