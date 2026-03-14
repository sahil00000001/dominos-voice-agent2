# 🍕 Domino's Pizza Voice AI Receptionist

A fully working, real-time voice AI agent that acts as a phone receptionist for Domino's Pizza India. You speak into your microphone, it listens, understands, and replies through your speakers — just like talking to a real person on a phone call.

---

## What It Does

When you run the program, an AI agent named **Priya** answers the call and:

1. Greets you and asks for your name
2. Takes your pizza order — one question at a time
3. Asks for your delivery address
4. Reads the full order back to confirm
5. Offers one upsell deal (Choco Lava Cake, Garlic Bread, Pepsi, etc.)
6. Gives a 30–45 minute delivery estimate and **automatically ends the call**

All of this happens through **real voice** — you speak, it listens, it talks back.

---

## Tech Stack

| Layer | Service | Why |
|---|---|---|
| **Speech-to-Text** | Deepgram | Fast, accurate, free tier available |
| **AI Brain** | Groq (llama-3.3-70b-versatile) | Ultra-fast inference, free tier |
| **Text-to-Speech** | Cartesia | Natural warm voice, low latency, free tier |
| **Framework** | Pipecat 0.0.105 | Real-time voice pipeline framework |
| **Dashboard** | FastAPI + WebSocket | Live browser dashboard at localhost:8000 |

---

## Project Structure

```
dominos-voice-agent2/
├── main.py           ← Pipeline setup, echo-fix strategy, call-end logic
├── tools.py          ← Order functions the LLM can call (confirm, upsell, finalise)
├── system_prompt.py  ← Priya's personality, menu, and call script
├── ui.py             ← Pipecat FrameProcessor that drives the dashboard state
├── web_ui.py         ← FastAPI + WebSocket server, broadcasts events to browser
├── static/
│   └── index.html    ← Browser dashboard UI
├── requirements.txt  ← All Python dependencies
├── .env.example      ← Template for API keys
└── .env              ← Your actual API keys (never commit this file)
```

---

## How It Works — The Pipeline

```
Your Microphone
      ↓
Deepgram STT       ← converts your speech to text in real time
      ↓
User Aggregator    ← waits for speech pause (0.8s), mutes mic while bot speaks
      ↓
Groq LLM           ← generates Priya's reply (may call tools)
      ↓
Cartesia TTS       ← converts text to natural speech audio
      ↓
Your Speakers
      ↓
Assistant Aggregator  ← stores reply in conversation memory
      ↓
UI Observer           ← updates the live browser dashboard
```

**Echo prevention:** A `DelayedUnmuteStrategy` keeps the microphone muted for 800 ms after the bot finishes speaking, preventing Priya's own voice from being picked up and sent back to the LLM.

---

## The Three AI Tools (Function Calling)

The LLM can call these Python functions mid-conversation:

### `confirm_order`
Called when the customer confirms their full order and address.
- Logs: customer name, items, delivery address, total price
- Tells the LLM: "Order confirmed, ask one upsell question"

### `add_upsell_item`
Called when the customer accepts an upsell offer.
- Logs: item name and price
- Tells the LLM: "Item added, say the closing line"

### `finalise_order`
Called at the very end of the call after the closing line.
- Logs: final order summary and estimated delivery time
- **Automatically shuts down the pipeline** after 3 seconds (call ends)

These appear in the **ORDER EVENTS** panel on the browser dashboard in real time.

---

## The Browser Dashboard

When running, your browser opens at `http://localhost:8000` and shows:

- **Status indicator** — IDLE / LISTENING / THINKING / SPEAKING (animated)
- **Live conversation** — both your messages and Priya's replies appear in real time
- **Order events panel** — confirm / upsell / finalise events with timestamps
- **Stats bar** — call count, orders, revenue, upsells

---

## Setup (First Time)

### Step 1 — Get Free API Keys

| Service | Link | Notes |
|---|---|---|
| Deepgram | https://console.deepgram.com | Sign up → copy API Key |
| Groq | https://console.groq.com/keys | Sign up → Create API key |
| Cartesia | https://play.cartesia.ai | Sign up → Settings → API Keys |

### Step 2 — Install Python 3.12

Download from: https://python.org/downloads/release/python-3120
**Important:** Check "Add Python to PATH" during install.

### Step 3 — Clone and set up the project

```powershell
git clone https://github.com/sahil00000001/dominos-voice-agent2.git
cd dominos-voice-agent2

python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

### Step 4 — Add Your API Keys

```powershell
copy .env.example .env
notepad .env
```

Fill in your three keys:

```env
DEEPGRAM_API_KEY=dg_xxxxxxxxxxxxxxxxxxxx
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxx
CARTESIA_API_KEY=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

---

## Running the Agent

```powershell
# Activate the virtual environment (only needed once per terminal session)
.\.venv\Scripts\Activate.ps1

# Run the agent
python main.py
```

The browser dashboard opens automatically at **http://localhost:8000**.
Speak into your microphone. Press **Ctrl+C** to end the session.

> **Tip:** Use **headphones** for the best experience. Without headphones, the microphone can pick up Priya's voice from the speakers. The `DelayedUnmuteStrategy` reduces this significantly, but headphones eliminate it completely.

---

## Every Time You Come Back

```powershell
cd dominos-voice-agent2
.\.venv\Scripts\Activate.ps1
python main.py
```

---

## Menu

| Pizza | Regular | Medium | Large |
|---|---|---|---|
| Margherita | ₹199 | ₹299 | ₹499 |
| Farmhouse | ₹249 | ₹349 | ₹549 |
| Veggie Paradise | ₹249 | ₹349 | ₹549 |
| Paneer Makhani | ₹279 | ₹379 | ₹599 |
| Double Cheese Margherita | ₹229 | ₹329 | ₹529 |
| Chicken Dominator | ₹299 | ₹399 | ₹649 |
| Pepper Barbeque Chicken | ₹279 | ₹379 | ₹599 |
| Chicken Golden Delight | ₹269 | ₹369 | ₹579 |
| Keema Do Pyaza | ₹299 | ₹399 | ₹649 |

**Sides & Drinks (upsell):** Garlic Bread ₹79 · Choco Lava Cake ₹49 · Pepsi ₹30

---

## Customisation

- **Change Priya's voice** — Browse voices at https://play.cartesia.ai and replace `voice_id` in `main.py`
- **Change the menu** — Edit `system_prompt.py`
- **Change the personality** — Edit the call flow rules in `system_prompt.py`
- **Connect to a real POS** — Replace the log calls in `tools.py` with actual API calls to your ordering system

---

## Dependencies

```
pipecat-ai[cartesia,deepgram,groq,local]  ← core framework + all services
torch (CPU)                                ← powers the Silero VAD model
python-dotenv                              ← loads API keys from .env
fastapi + uvicorn                          ← web dashboard server
```

---

*Built with Pipecat · Groq (Llama 3.3 70B) · Deepgram · Cartesia*
