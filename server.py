"""Mini AI Voice KAM: FastAPI backend.

Browser does speech-to-text (Web Speech API) and sends text to /chat.
Here Claude runs a tool loop over mock seller data and streams each step back as it happens.
/tts turns the reply into speech.
"""
import json
import os
import pathlib
import urllib.request
import uuid
from collections import Counter
from datetime import date, datetime, timedelta

import anthropic
import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel

HERE = pathlib.Path(__file__).parent

# Tiny .env loader (KEY=VALUE lines), avoids an extra dependency
if (HERE / ".env").exists():
    for line in (HERE / ".env").read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

MODEL = os.environ.get("KAM_MODEL", "claude-haiku-5-5")  # fast model for voice turns
SYSTEM_PROMPT = (HERE / "prompt.md").read_text(encoding="utf-8")
client = anthropic.Anthropic()

# ---------------------------------------------------------------- mock data
# The five headline numbers come straight from the assignment.
# Everything under "detail" is an ASSUMPTION added to make the diagnosis concrete (see NOTE.md).
SELLER = {
    "seller": "Sharma Home Decor",
    "category": "Home & Kitchen",
    "catalogue_size": 60,
    "last_month": {"sales": 200000, "orders": 400, "cancellation_rate": 0.08, "avg_price": 500, "oos_products": 5},
    "this_month": {"sales": 135000, "orders": 270, "cancellation_rate": 0.14, "avg_price": 500, "oos_products": 18},
    "detail": {
        # 13 SKUs went out of stock this month. Last month they sold 150 orders; this month only 20 (before they ran out).
        "newly_oos_skus": [
            {"sku": "HD-101", "name": "Cotton bedsheet set (double)", "orders_last_month": 34, "orders_this_month": 4, "supplier": "Jaipur Textiles"},
            {"sku": "HD-107", "name": "Ceramic dinner set, 18 pc", "orders_last_month": 26, "orders_this_month": 3, "supplier": "Khurja Ceramics"},
            {"sku": "HD-112", "name": "Blackout curtains (pair)", "orders_last_month": 21, "orders_this_month": 3, "supplier": "Jaipur Textiles"},
            {"sku": "HD-118", "name": "Steel water bottle, 1 L", "orders_last_month": 17, "orders_this_month": 2, "supplier": "Rajkot Steelware"},
            {"sku": "HD-124", "name": "Cushion covers, set of 5", "orders_last_month": 14, "orders_this_month": 2, "supplier": "Jaipur Textiles"},
            {"sku": "HD-131", "name": "Bath towel set", "orders_last_month": 11, "orders_this_month": 2, "supplier": "Jaipur Textiles"},
            {"sku": "HD-133", "name": "Wall clock, wooden", "orders_last_month": 8, "orders_this_month": 1, "supplier": "Saharanpur Woodcraft"},
            {"sku": "HD-140", "name": "Kitchen storage jars, 6 pc", "orders_last_month": 6, "orders_this_month": 1, "supplier": "Rajkot Steelware"},
            {"sku": "HD-142", "name": "Table runner", "orders_last_month": 4, "orders_this_month": 1, "supplier": "Jaipur Textiles"},
            {"sku": "HD-147", "name": "Door mat, coir", "orders_last_month": 3, "orders_this_month": 1, "supplier": "Alleppey Coir"},
            {"sku": "HD-150", "name": "Fridge mats, set of 6", "orders_last_month": 2, "orders_this_month": 0, "supplier": "Rajkot Steelware"},
            {"sku": "HD-152", "name": "Napkin holder", "orders_last_month": 2, "orders_this_month": 0, "supplier": "Saharanpur Woodcraft"},
            {"sku": "HD-155", "name": "Coaster set", "orders_last_month": 2, "orders_this_month": 0, "supplier": "Saharanpur Woodcraft"},
        ],
        "other_skus_orders": {"last_month": 250, "this_month": 250},  # everything still in stock sold the same
        # Orders are counted gross (before cancellations). Reasons for cancelled orders:
        "cancellation_reasons": {
            "last_month": {"item_unavailable": 6, "dispatch_delay": 10, "customer_changed_mind": 16},
            "this_month": {"item_unavailable": 22, "dispatch_delay": 9, "customer_changed_mind": 7},
        },
        # Illustrative visibility signal for the in-stock catalogue
        "search_impressions": {"last_month": 52000, "this_month": 44200},
    },
}

TODAY = date.today()


def diagnose():
    """Deterministic diagnosis. The LLM explains it; it never does the arithmetic."""
    lm, tm, d = SELLER["last_month"], SELLER["this_month"], SELLER["detail"]
    pct = lambda a, b: round((b - a) / a * 100, 1)
    oos = d["newly_oos_skus"]
    lost_oos_orders = sum(s["orders_last_month"] - s["orders_this_month"] for s in oos)
    order_drop = lm["orders"] - tm["orders"]
    cancels_last = round(lm["orders"] * lm["cancellation_rate"])
    cancels_this = round(tm["orders"] * tm["cancellation_rate"])
    unavailable = d["cancellation_reasons"]["this_month"]["item_unavailable"]
    top = sorted(oos, key=lambda s: -s["orders_last_month"])
    suppliers = dict(Counter(s["supplier"] for s in oos))

    issues = [
        {
            "rank": 1,
            "issue": "Stock-outs on best sellers",
            "evidence": f"Out-of-stock products rose {lm['oos_products']} to {tm['oos_products']}. "
                        f"The {len(oos)} newly out-of-stock SKUs lost {lost_oos_orders} orders, "
                        f"which is {round(lost_oos_orders / order_drop * 100)}% of the {order_drop}-order drop.",
            "revenue_impact_inr": lost_oos_orders * tm["avg_price"],
            "restock_first": [{"sku": s["sku"], "name": s["name"], "supplier": s["supplier"],
                               "orders_lost": s["orders_last_month"] - s["orders_this_month"]} for s in top[:3]],
            "restock_first_orders_lost_total": sum(s["orders_last_month"] - s["orders_this_month"] for s in top[:3]),
            "suppliers_affected": suppliers,
        },
        {
            "rank": 2,
            "issue": "Cancellations up, mostly from unavailable items",
            "evidence": f"Cancellation rate went {lm['cancellation_rate']:.0%} to {tm['cancellation_rate']:.0%} "
                        f"({cancels_last} to {cancels_this} orders). {unavailable} of {cancels_this} cancellations "
                        f"this month were 'item unavailable', up from {d['cancellation_reasons']['last_month']['item_unavailable']}.",
            "revenue_impact_inr": cancels_this * tm["avg_price"],
        },
        {
            "rank": 3,
            "issue": "Visibility risk",
            "evidence": f"Search impressions fell {abs(pct(d['search_impressions']['last_month'], d['search_impressions']['this_month']))}%. "
                        "Stock-outs and seller-side cancellations usually lower search ranking, so this can get worse next month.",
        },
    ]
    return {
        "sales_change_pct": pct(lm["sales"], tm["sales"]),
        "orders_change_pct": pct(lm["orders"], tm["orders"]),
        "avg_price_change_pct": pct(lm["avg_price"], tm["avg_price"]),
        "headline": "Volume problem, not a pricing problem: price is flat and sales fell exactly in line with orders.",
        "root_cause": "Stock-outs on top SKUs. They lose orders directly, cause 'item unavailable' cancellations, and hurt visibility.",
        "not_the_cause": ["Pricing (avg price flat at ₹500)", f"In-stock SKUs (still {d['other_skus_orders']['this_month']} orders, unchanged)"],
        "issues": issues,
    }


def create_action_plan(session, actions):
    tasks = []
    for i, a in enumerate(actions, 1):
        due = TODAY + timedelta(days=int(a.get("due_in_days", 3)))
        tasks.append({"id": f"T{i}", "title": a["title"], "owner": a.get("owner", "Seller"),
                      "due": due.strftime("%a %d %b"), "kpi": a.get("kpi", "")})
    session["plan"]["tasks"] = tasks
    return {"created": len(tasks), "tasks": tasks}


def schedule_follow_up(session, days, kpis):
    when = datetime.combine(TODAY + timedelta(days=int(days)), datetime.min.time()).replace(hour=11)
    session["plan"]["follow_up"] = {"when": when.strftime("%a %d %b, %I:%M %p"), "kpis": kpis}
    return {"booked": True, **session["plan"]["follow_up"]}


def raise_restock_alert(session, sku_ids):
    known = {s["sku"]: s for s in SELLER["detail"]["newly_oos_skus"]}
    alerts = [{"sku": k, "name": known[k]["name"], "supplier": known[k]["supplier"]} for k in sku_ids if k in known]
    session["plan"]["restock_alerts"] = alerts
    return {"alerts_raised": len(alerts), "suppliers_notified": sorted({a["supplier"] for a in alerts}), "alerts": alerts, "unknown": [k for k in sku_ids if k not in known]}


TOOLS = [
    {"name": "get_seller_metrics", "description": "Get this seller's last-month vs this-month metrics plus SKU-level detail (out-of-stock SKUs, cancellation reasons, impressions).",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "diagnose", "description": "Run the deterministic diagnosis: computes all deltas and returns ranked issues with evidence. Always use its numbers; never compute them yourself.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "raise_restock_alert", "description": "Raise restock alerts to the seller's suppliers for specific out-of-stock SKUs.",
     "input_schema": {"type": "object", "properties": {"sku_ids": {"type": "array", "items": {"type": "string"}}}, "required": ["sku_ids"]}},
    {"name": "create_action_plan", "description": "Create the agreed action plan as tasks. Call only after the seller agrees. 2-4 tasks.",
     "input_schema": {"type": "object", "properties": {"actions": {"type": "array", "items": {"type": "object", "properties": {
         "title": {"type": "string"}, "owner": {"type": "string", "description": "Seller, or KAM (you)"},
         "due_in_days": {"type": "integer"}, "kpi": {"type": "string", "description": "measurable target"}},
         "required": ["title", "owner", "due_in_days", "kpi"]}}}, "required": ["actions"]}},
    {"name": "schedule_follow_up", "description": "Book a follow-up call to check KPIs.",
     "input_schema": {"type": "object", "properties": {"days": {"type": "integer"}, "kpis": {"type": "array", "items": {"type": "string"}}}, "required": ["days", "kpis"]}},
]


# name -> function(session, args). get_seller_metrics is where a real seller API would plug in.
TOOL_FUNCS = {
    "get_seller_metrics": lambda session, args: SELLER,
    "diagnose": lambda session, args: diagnose(),
    "raise_restock_alert": lambda session, args: raise_restock_alert(session, args["sku_ids"]),
    "create_action_plan": lambda session, args: create_action_plan(session, args["actions"]),
    "schedule_follow_up": lambda session, args: schedule_follow_up(session, args["days"], args["kpis"]),
}


# ---------------------------------------------------------------- agent loop
GREETING = "Hello, this is Kai, your account manager. How can I help you today?"
# Spoken while the first tool of a turn runs, if Claude didn't say anything itself
FILLERS = {
    "get_seller_metrics": "Sure, let me pull up your account.",
    "diagnose": "Sure, let me pull up your account.",
    "raise_restock_alert": "On it, setting that up now.",
    "create_action_plan": "On it, setting that up now.",
}
SESSIONS = {}  # in-memory, single process; move to Redis if it ever runs multi-instance


def agent_turn(session, user_text):
    """One seller turn. Yields events as they happen so the UI can show the agent working:
    {"type": "say"}   a short line Claude speaks before using tools ("Let me pull up your account")
    {"type": "tool"}  a tool that just ran, with its input and output
    {"type": "reply"} the final spoken answer plus the current action plan
    """
    if not session["messages"]:  # call just connected: fixed greeting, no model call needed
        session["messages"] += [{"role": "user", "content": "[call connected]"}, {"role": "assistant", "content": GREETING}]
        yield {"type": "reply", "text": GREETING, "plan": session["plan"]}
        return
    session["messages"].append({"role": "user", "content": user_text})
    spoke = False
    for _ in range(8):  # cap tool rounds per turn
        resp = client.messages.create(
            model=MODEL, max_tokens=2000, system=SYSTEM_PROMPT, tools=TOOLS,
            messages=session["messages"], output_config={"effort": "low"},
        )
        session["messages"].append({"role": "assistant", "content": resp.content})
        text = " ".join(b.text for b in resp.content if b.type == "text").strip()
        if resp.stop_reason != "tool_use":
            yield {"type": "reply", "text": text, "plan": session["plan"]}
            return
        if not text and not spoke:  # nothing said yet this turn: acknowledge so the seller isn't left in silence
            text = FILLERS.get(next(b.name for b in resp.content if b.type == "tool_use"), "")
        if text:
            spoke = True
            yield {"type": "say", "text": text}
        results = []
        for b in resp.content:
            if b.type != "tool_use":
                continue
            try:
                out, err = TOOL_FUNCS[b.name](session, b.input), False
            except Exception as e:  # tell Claude, don't crash the call
                out, err = {"error": f"{type(e).__name__}: {e}"}, True
            yield {"type": "tool", "tool": b.name, "input": b.input, "output": out, "plan": session["plan"]}
            results.append({"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(out), "is_error": err})
        session["messages"].append({"role": "user", "content": results})
    yield {"type": "reply", "text": "Sorry, I got stuck there. Could you say that again?", "plan": session["plan"]}


# ---------------------------------------------------------------- web
app = FastAPI()


class Chat(BaseModel):
    session_id: str | None = None
    text: str


@app.get("/")
def index():
    return FileResponse(HERE / "index.html")


@app.post("/chat")
def chat(body: Chat):
    """Streams one JSON object per line (NDJSON): session id first, then the events from agent_turn."""
    sid = body.session_id or str(uuid.uuid4())
    session = SESSIONS.setdefault(sid, {"messages": [], "plan": {}})

    def stream():
        n = len(session["messages"])
        yield json.dumps({"type": "session", "session_id": sid}) + "\n"
        try:
            for event in agent_turn(session, body.text[:2000]):
                yield json.dumps(event) + "\n"
        except Exception as e:  # e.g. missing key, rate limit: show it in the UI
            del session["messages"][n:]  # roll back this turn so the seller can just say it again
            yield json.dumps({"type": "error", "text": f"{type(e).__name__}: {e}"}) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")


class TTS(BaseModel):
    text: str


@app.post("/tts")
def tts(body: TTS):
    """ElevenLabs if a key is set; otherwise 204 and the browser uses its own voice."""
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        return Response(status_code=204)
    voice = os.environ.get("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=mp3_44100_128",
        data=json.dumps({"text": body.text[:1500], "model_id": "eleven_flash_v2_5"}).encode(),
        headers={"xi-api-key": key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return Response(r.read(), media_type="audio/mpeg")
    except Exception:
        return Response(status_code=204)  # fall back to browser voice


if __name__ == "__main__":
    import sys
    if "--check" in sys.argv:  # self-check of the deterministic parts (no API calls)
        d = diagnose()
        assert d["sales_change_pct"] == -32.5 and d["orders_change_pct"] == -32.5 and d["avg_price_change_pct"] == 0
        assert "130 orders" in d["issues"][0]["evidence"] and "100%" in d["issues"][0]["evidence"]
        assert sum(s["orders_this_month"] for s in SELLER["detail"]["newly_oos_skus"]) + 250 == 270
        assert len(SELLER["detail"]["newly_oos_skus"]) + SELLER["last_month"]["oos_products"] == 18
        assert sum(SELLER["detail"]["cancellation_reasons"]["this_month"].values()) == round(270 * 0.14)
        assert sum(SELLER["detail"]["cancellation_reasons"]["last_month"].values()) == round(400 * 0.08)
        assert {t["name"] for t in TOOLS} == set(TOOL_FUNCS)
        s = {"plan": {}}
        r = TOOL_FUNCS["raise_restock_alert"](s, {"sku_ids": ["HD-101", "NOPE"]})
        assert r["alerts_raised"] == 1 and r["unknown"] == ["NOPE"] and r["suppliers_notified"] == ["Jaipur Textiles"]
        r = TOOL_FUNCS["create_action_plan"](s, {"actions": [{"title": "Restock", "owner": "Seller", "due_in_days": 7, "kpi": "OOS < 5"}]})
        assert r["created"] == 1 and s["plan"]["tasks"][0]["due"] == (TODAY + timedelta(days=7)).strftime("%a %d %b")
        r = TOOL_FUNCS["schedule_follow_up"](s, {"days": 7, "kpis": ["OOS < 5"]})
        assert r["booked"] and "11:00 AM" in s["plan"]["follow_up"]["when"]
        print("self-check OK:", d["headline"])
    else:
        uvicorn.run(app, host="127.0.0.1", port=8000)
