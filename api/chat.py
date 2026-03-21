"""
api/chat.py — Groq LLM serverless endpoint
==========================================
Receives conversation history from the browser, calls Groq with tool support,
executes any tool calls (confirm_order, add_upsell_item, finalise_order),
and returns the assistant's text reply plus updated history and tool events.
"""

from http.server import BaseHTTPRequestHandler
import json
import os
import urllib.request
import urllib.error

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

# ── Tool definitions (OpenAI-compatible format for Groq) ──────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "confirm_order",
            "description": (
                "Call this tool once the customer has verbally confirmed their full order "
                "and delivery address. Pass all order details and the calculated total."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_name": {
                        "type": "string",
                        "description": "The customer's first name.",
                    },
                    "order_items": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of ordered items with quantities, e.g. ['1x Farmhouse Pizza (Medium)'].",
                    },
                    "delivery_address": {
                        "type": "string",
                        "description": "The customer's full delivery address as spoken.",
                    },
                    "order_total_inr": {
                        "type": "number",
                        "description": "The calculated order total in Indian Rupees.",
                    },
                },
                "required": ["customer_name", "order_items", "delivery_address", "order_total_inr"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_upsell_item",
            "description": "Call this tool when the customer agrees to an upsell offer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_name": {
                        "type": "string",
                        "description": "Name of the upsell item, e.g. 'Choco Lava Cake'.",
                    },
                    "item_price_inr": {
                        "type": "number",
                        "description": "Price of the upsell item in Indian Rupees.",
                    },
                },
                "required": ["item_name", "item_price_inr"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finalise_order",
            "description": (
                "Call this tool at the very end of the call after thanking the customer "
                "and giving the delivery estimate. This closes the order."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_name": {
                        "type": "string",
                        "description": "The customer's first name.",
                    },
                    "final_order_summary": {
                        "type": "string",
                        "description": "A complete human-readable summary of everything ordered.",
                    },
                    "estimated_delivery_minutes": {
                        "type": "integer",
                        "description": "Estimated delivery time in minutes. Default is 35.",
                    },
                },
                "required": ["customer_name", "final_order_summary"],
            },
        },
    },
]


# ── Tool execution ─────────────────────────────────────────────────────────────

def execute_tool(name: str, args: dict):
    """Execute a tool call and return (result_string, event_dict_or_None)."""
    if name == "confirm_order":
        customer = args.get("customer_name", "Customer")
        items = args.get("order_items", [])
        address = args.get("delivery_address", "")
        total = float(args.get("order_total_inr", 0))
        return (
            f"Order logged. Total: ₹{total:.2f}. "
            "DO NOT repeat or summarise the order. "
            "Ask ONE upsell question now (single short sentence).",
            {
                "type": "confirmed",
                "customer": customer,
                "items": items,
                "address": address,
                "total": total,
            },
        )

    elif name == "add_upsell_item":
        item = args.get("item_name", "item")
        price = float(args.get("item_price_inr", 0))
        return (
            f"{item} added. Updated total includes ₹{price:.0f}. "
            "DO NOT repeat or summarise the order. "
            "Say ONLY the closing line: delivery in 30-45 minutes, thank by name, goodbye. "
            "Then call finalise_order immediately.",
            {"type": "upsell", "item": item, "price": price},
        )

    elif name == "finalise_order":
        customer = args.get("customer_name", "Customer")
        summary = args.get("final_order_summary", "")
        eta = int(args.get("estimated_delivery_minutes", 35))
        return (
            "Order finalised. Call complete. Say nothing more.",
            {"type": "finalised", "customer": customer, "summary": summary, "eta": eta},
        )

    return ("OK", None)


# ── Groq API call ──────────────────────────────────────────────────────────────

def groq_request(messages: list, use_tools: bool, groq_key: str) -> dict:
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": messages,
        "max_tokens": 200,
        "stream": False,
    }
    if use_tools:
        payload["tools"] = TOOLS
        payload["tool_choice"] = "auto"

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=data,
        headers={
            "Authorization": f"Bearer {groq_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read())


# ── HTTP handler ───────────────────────────────────────────────────────────────

class handler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            client_messages = body.get("messages", [])
            groq_key = os.environ.get("GROQ_API_KEY", "")

            # Full message list: system + client history
            all_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + client_messages

            tool_events = []
            call_ended = False
            reply_text = ""

            # Agentic tool loop — keep calling until no more tool_calls
            for _ in range(6):
                result = groq_request(all_messages, use_tools=True, groq_key=groq_key)
                msg = result["choices"][0]["message"]
                all_messages.append(msg)

                if not msg.get("tool_calls"):
                    reply_text = msg.get("content") or ""
                    break

                # Execute each tool call
                for tc in msg["tool_calls"]:
                    name = tc["function"]["name"]
                    args = json.loads(tc["function"]["arguments"])
                    tool_result, event = execute_tool(name, args)

                    if event:
                        tool_events.append(event)
                        if event["type"] == "finalised":
                            call_ended = True

                    all_messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": tool_result,
                    })

            # Strip system message before returning to client
            updated_history = [m for m in all_messages if m.get("role") != "system"]

            self._json(200, {
                "text": reply_text,
                "tool_events": tool_events,
                "messages": updated_history,
                "call_ended": call_ended,
            })

        except Exception as exc:
            self._json(500, {"error": str(exc), "text": "", "tool_events": [], "messages": [], "call_ended": False})

    def _json(self, status: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, *args):
        pass  # silence access logs
