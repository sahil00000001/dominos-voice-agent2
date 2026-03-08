"""
tools.py — Domino's Pizza Voice Agent Tool Definitions
=======================================================
Defines the three order-management functions that Gemini can call during a
conversation, plus a get_tool_definitions() factory that returns them as a
Pipecat ToolsSchema.

Each handler is an async function that receives a FunctionCallParams object
from Pipecat. It executes business logic and returns a result string back to
the LLM via params.result_callback(), which causes Gemini to continue the
conversation with that result injected as context.

Order events are also pushed to the UI log panel via ui.add_log().
"""

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.services.llm_service import FunctionCallParams

# Push order events into the UI's ORDER EVENTS panel (set up by main.py)
from ui import add_log


# ---------------------------------------------------------------------------
# Tool Handler Functions
# Registered on the LLM service via llm.register_function() in main.py.
# ---------------------------------------------------------------------------

async def confirm_order(params: FunctionCallParams) -> None:
    """
    Called by Gemini once the customer confirms their full order and address.

    Expected arguments:
        customer_name      (str)        — Customer's first name
        order_items        (list[str])  — e.g. ["1x Farmhouse Pizza", "1x Pepsi"]
        delivery_address   (str)        — Full delivery address
        order_total_inr    (float)      — Order total in Indian Rupees
    """
    args = params.arguments

    customer_name    = args.get("customer_name", "Customer")
    order_items      = args.get("order_items", [])
    delivery_address = args.get("delivery_address", "")
    order_total_inr  = args.get("order_total_inr", 0.0)

    # Push to the UI's ORDER EVENTS panel
    add_log(f"[bold green]✔ ORDER CONFIRMED[/bold green]  {customer_name}  ·  "
            f"₹{order_total_inr:.0f}  ·  {', '.join(order_items)}")
    add_log(f"  [dim]📍 Delivering to:[/dim] {delivery_address}")

    await params.result_callback(
        f"Order confirmed for {customer_name}. "
        f"Total: ₹{order_total_inr:.2f}. Proceed to upsell."
    )


async def add_upsell_item(params: FunctionCallParams) -> None:
    """
    Called by Gemini when the customer accepts an upsell offer.

    Expected arguments:
        item_name      (str)   — e.g. "Choco Lava Cake"
        item_price_inr (float) — Price in Indian Rupees
    """
    args = params.arguments

    item_name      = args.get("item_name", "item")
    item_price_inr = args.get("item_price_inr", 0.0)

    add_log(f"[bold yellow]➕ UPSELL ADDED[/bold yellow]  {item_name}  ·  ₹{item_price_inr:.0f}")

    await params.result_callback(
        f"{item_name} (₹{item_price_inr:.2f}) added to the order. "
        "Proceed to give delivery estimate and close the call."
    )


async def finalise_order(params: FunctionCallParams) -> None:
    """
    Called by Gemini at the very end of the call after thanking the customer.

    Expected arguments:
        customer_name              (str) — Customer's first name
        final_order_summary        (str) — Full human-readable summary
        estimated_delivery_minutes (int) — Delivery ETA (default 35)
    """
    args = params.arguments

    customer_name              = args.get("customer_name", "Customer")
    final_order_summary        = args.get("final_order_summary", "")
    estimated_delivery_minutes = args.get("estimated_delivery_minutes", 35)

    add_log(f"[bold cyan]🏁 ORDER FINALISED[/bold cyan]  {customer_name}  "
            f"·  ETA {estimated_delivery_minutes} min")
    add_log(f"  [dim]{final_order_summary}[/dim]")

    await params.result_callback(
        f"Order finalised for {customer_name}. "
        f"Delivery in ~{estimated_delivery_minutes} minutes. Call complete."
    )


# ---------------------------------------------------------------------------
# Tool Schema Definitions
# ---------------------------------------------------------------------------

def get_tool_definitions() -> ToolsSchema:
    """
    Returns a ToolsSchema containing all three Domino's order-management tools,
    formatted as Pipecat FunctionSchema objects compatible with Gemini function calling.
    """

    confirm_order_schema = FunctionSchema(
        name="confirm_order",
        description=(
            "Call this tool once the customer has verbally confirmed their full order "
            "and delivery address. Pass all order details and the calculated total."
        ),
        properties={
            "customer_name": {
                "type": "string",
                "description": "The customer's first name.",
            },
            "order_items": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "List of ordered items with quantities, "
                    "e.g. ['1x Farmhouse Pizza (Medium)', '1x Pepsi']."
                ),
            },
            "delivery_address": {
                "type": "string",
                "description": "The customer's full delivery address as spoken.",
            },
            "order_total_inr": {
                "type": "number",
                "description": "The calculated order total in Indian Rupees (float).",
            },
        },
        required=["customer_name", "order_items", "delivery_address", "order_total_inr"],
    )

    add_upsell_item_schema = FunctionSchema(
        name="add_upsell_item",
        description=(
            "Call this tool when the customer agrees to an upsell offer. "
            "Pass the item name and its price."
        ),
        properties={
            "item_name": {
                "type": "string",
                "description": "Name of the upsell item, e.g. 'Choco Lava Cake'.",
            },
            "item_price_inr": {
                "type": "number",
                "description": "Price of the upsell item in Indian Rupees.",
            },
        },
        required=["item_name", "item_price_inr"],
    )

    finalise_order_schema = FunctionSchema(
        name="finalise_order",
        description=(
            "Call this tool at the very end of the call after thanking the customer "
            "and giving the delivery estimate. This closes the order."
        ),
        properties={
            "customer_name": {
                "type": "string",
                "description": "The customer's first name.",
            },
            "final_order_summary": {
                "type": "string",
                "description": (
                    "A complete human-readable summary of everything ordered, "
                    "including any upsell items and the final total."
                ),
            },
            "estimated_delivery_minutes": {
                "type": "integer",
                "description": "Estimated delivery time in minutes. Default is 35.",
            },
        },
        required=["customer_name", "final_order_summary"],
    )

    return ToolsSchema(
        standard_tools=[
            confirm_order_schema,
            add_upsell_item_schema,
            finalise_order_schema,
        ]
    )
