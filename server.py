"""Mini AI Voice KAM: FastAPI backend.

Browser does speech-to-text (Web Speech API, improved by /stt) and sends text to /chat.
Here Claude runs a tool loop over mock seller data and streams each step back as it happens.
/tts turns the reply into speech.
"""
import json
import os
import pathlib
import re
import time
import urllib.request
import uuid
from collections import Counter
from datetime import date, datetime, timedelta

import anthropic
import uvicorn
from fastapi import FastAPI, Header, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel

HERE = pathlib.Path(__file__).parent

# Tiny .env loader (KEY=VALUE lines), avoids an extra dependency.
# utf-8-sig drops the invisible BOM Windows Notepad can add; quotes around values are removed.
if (HERE / ".env").exists():
    for line in (HERE / ".env").read_text(encoding="utf-8-sig").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

MODEL = os.environ.get("KAM_MODEL", "claude-haiku-5-5")  # fast model for voice turns
ACCESS_CODE = os.environ.get("ACCESS_CODE", "")  # set this before putting the app on a public link
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

def pct_change(before, after):
    """Percent change, or None when there is no 'before' to compare with."""
    return round((after - before) / before * 100, 1) if before else None


def diagnose(data=None):
    """Deterministic diagnosis. The LLM explains it; it never does the arithmetic.

    Works on any seller data with the same shape: every number, the headline, the root cause
    and the ranking are computed here. Issues are ranked by the revenue they cost this month.
    """
    data = data or SELLER
    lm, tm, d = data["last_month"], data["this_month"], data.get("detail", {})
    price = tm["avg_price"]
    sales_pct, orders_pct, price_pct = (pct_change(lm[k], tm[k]) for k in ("sales", "orders", "avg_price"))
    order_drop = lm["orders"] - tm["orders"]
    issues = []

    # 1. Stock-outs: orders lost on products that ran out this month
    oos = sorted(d.get("newly_oos_skus", []), key=lambda s: -(s["orders_last_month"] - s["orders_this_month"]))
    lost_oos = sum(max(0, s["orders_last_month"] - s["orders_this_month"]) for s in oos)
    if lost_oos or tm["oos_products"] > lm["oos_products"]:
        share = f", {round(lost_oos / order_drop * 100)}% of the {order_drop}-order drop" if order_drop > 0 else ""
        top3 = [s for s in oos[:3] if s["orders_last_month"] > s["orders_this_month"]]
        issues.append({
            "issue": "Stock-outs on best sellers",
            "evidence": f"Out-of-stock products went from {lm['oos_products']} to {tm['oos_products']}. "
                        f"The {len(oos)} products that ran out this month lost {lost_oos} orders{share}.",
            "revenue_lost_inr": lost_oos * price,
            "restock_first": [{"sku": s["sku"], "name": s["name"], "supplier": s["supplier"],
                               "orders_lost": s["orders_last_month"] - s["orders_this_month"]} for s in top3],
            "restock_first_orders_lost_total": sum(s["orders_last_month"] - s["orders_this_month"] for s in top3),
            "suppliers_affected": dict(Counter(s["supplier"] for s in oos)),
            "suggested_actions": ["Restock the top products and alert their suppliers",
                                  "Turn on low-stock alerts or mark items unavailable so new orders aren't cancelled"],
        })

    # 2. Pricing: a lower price loses revenue on every order; a higher price may cost orders
    if price_pct is not None and price_pct <= -3:
        issues.append({
            "issue": "Lower selling price",
            "evidence": f"Average price fell from {lm['avg_price']} to {price} rupees ({price_pct}%).",
            "revenue_lost_inr": (lm["avg_price"] - price) * tm["orders"],
            "suggested_actions": ["Review recent discounts and restore prices where margin allows"],
        })
    elif price_pct is not None and price_pct >= 3 and order_drop > lost_oos:
        unexplained = order_drop - lost_oos
        issues.append({
            "issue": "Higher price may be costing orders",
            "evidence": f"Average price rose from {lm['avg_price']} to {price} rupees (+{price_pct}%), and "
                        f"{unexplained} lost orders are not explained by stock-outs.",
            "revenue_lost_inr": unexplained * price,
            "suggested_actions": ["Compare prices with similar listings and test a lower price on top products"],
        })

    # 3. Cancellations: extra orders cancelled because the rate went up.
    #    Not double counted with stock-outs: those are orders never placed; these were placed, then cancelled.
    rate_up = round((tm["cancellation_rate"] - lm["cancellation_rate"]) * 100, 1)
    if rate_up >= 1:
        reasons = d.get("cancellation_reasons", {})
        top_reason = max(reasons.get("this_month", {"unknown": 0}).items(), key=lambda kv: kv[1])
        before = reasons.get("last_month", {}).get(top_reason[0], 0)
        issues.append({
            "issue": "More cancellations",
            "evidence": f"Cancellation rate went from {lm['cancellation_rate']:.0%} to {tm['cancellation_rate']:.0%} "
                        f"({round(lm['orders'] * lm['cancellation_rate'])} to {round(tm['orders'] * tm['cancellation_rate'])} orders). "
                        f"Top reason this month: {top_reason[0].replace('_', ' ')} ({top_reason[1]}, up from {before}).",
            "revenue_lost_inr": round(rate_up / 100 * tm["orders"]) * price,
            "suggested_actions": [f"Fix the main cancellation reason: {top_reason[0].replace('_', ' ')}"],
        })

    # 4. Visibility: fewer orders on products that stayed in stock, or fewer search impressions
    other = d.get("other_skus_orders", {})
    lost_in_stock = max(0, other.get("last_month", 0) - other.get("this_month", 0))
    imp = d.get("search_impressions", {})
    imp_pct = pct_change(imp.get("last_month", 0), imp.get("this_month", 0))
    if lost_in_stock or (imp_pct is not None and imp_pct <= -5):
        issues.append({
            "issue": "Lower visibility",
            "evidence": (f"Search impressions changed {imp_pct}%. " if imp_pct is not None else "")
                        + f"Products that stayed in stock lost {lost_in_stock} orders.",
            "revenue_lost_inr": lost_in_stock * price,
            "suggested_actions": ["Run sponsored listings or deals on top products once they are in stock"],
        })

    issues.sort(key=lambda i: -i["revenue_lost_inr"])  # biggest money first
    for n, issue in enumerate(issues, 1):
        issue["rank"] = n

    # Headline: is this a volume problem, a price problem, or not a problem at all?
    if sales_pct is None or sales_pct >= 0:
        headline = f"Sales did not drop (change: {sales_pct}%)."
    elif price_pct is not None and abs(price_pct) < 3:
        headline = f"Volume problem, not a pricing problem: price is flat and orders fell {abs(orders_pct)}%."
    elif orders_pct is not None and orders_pct > -3:
        headline = f"Price problem: orders held steady but average price fell {abs(price_pct)}%."
    else:
        headline = f"Both fewer orders ({orders_pct}%) and a price change ({price_pct}%) moved sales."

    not_the_cause = []
    if price_pct is not None and abs(price_pct) < 3:
        not_the_cause.append(f"Pricing (average price {lm['avg_price']} to {price} rupees)")
    if other and not lost_in_stock:
        not_the_cause.append(f"Products that stayed in stock ({other.get('this_month')} orders, not down)")

    return {
        "sales_change_pct": sales_pct, "orders_change_pct": orders_pct, "avg_price_change_pct": price_pct,
        "headline": headline,
        "root_cause": f"{issues[0]['issue']}: {issues[0]['evidence']}" if issues else "No clear cause in this data.",
        "not_the_cause": not_the_cause,
        "issues": issues,
    }


def create_action_plan(session, actions):
    """Adds tasks to the plan. Calling it again adds more; a task with the same title is updated."""
    if not actions:
        raise ValueError("actions is empty: pass at least one task")
    tasks = {t["title"].lower(): t for t in session["plan"].get("tasks", [])}
    for a in actions:
        days = int(a.get("due_in_days", 3))
        if not 0 <= days <= 90:
            raise ValueError(f"due_in_days must be between 0 and 90, got {days}")
        tasks[a["title"].lower()] = {"title": a["title"], "owner": a.get("owner", "Seller"),
                                     "due": (date.today() + timedelta(days=days)).strftime("%a %d %b"),
                                     "kpi": a.get("kpi", "")}
    session["plan"]["tasks"] = [{"id": f"T{n}", **t} for n, t in enumerate(tasks.values(), 1)]
    return {"added": len(actions), "tasks": session["plan"]["tasks"]}


def schedule_follow_up(session, days, kpis):
    days = int(days)
    if not 1 <= days <= 60:
        raise ValueError(f"days must be between 1 and 60, got {days}")
    when = datetime.combine(date.today() + timedelta(days=days), datetime.min.time()).replace(hour=11)
    session["plan"]["follow_up"] = {"when": when.strftime("%a %d %b, %I:%M %p"), "kpis": kpis}
    return {"booked": True, **session["plan"]["follow_up"]}


def raise_restock_alert(session, sku_ids):
    """Alerts suppliers. Calling it again adds to the alerts already raised in this call."""
    known = {s["sku"]: s for s in SELLER["detail"].get("newly_oos_skus", [])}
    alerts = {a["sku"]: a for a in session["plan"].get("restock_alerts", [])}
    for k in sku_ids:
        if k in known:
            alerts[k] = {"sku": k, "name": known[k]["name"], "supplier": known[k]["supplier"]}
    session["plan"]["restock_alerts"] = list(alerts.values())
    new = [alerts[k] for k in sku_ids if k in known]
    return {"alerts_raised": len(new), "suppliers_notified": sorted({a["supplier"] for a in new}),
            "alerts": new, "unknown": [k for k in sku_ids if k not in known]}


TOOLS = [
    {"name": "get_seller_metrics", "description": "Get this seller's last-month vs this-month metrics plus SKU-level detail (out-of-stock SKUs, cancellation reasons, impressions).",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "diagnose", "description": "Run the deterministic diagnosis: computes all deltas and returns ranked issues with evidence. Always use its numbers; never compute them yourself.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "raise_restock_alert", "description": "Raise restock alerts to the seller's suppliers for specific out-of-stock SKUs.",
     "input_schema": {"type": "object", "properties": {"sku_ids": {"type": "array", "items": {"type": "string"}}}, "required": ["sku_ids"]}},
    {"name": "create_action_plan", "description": "Add the agreed tasks to the action plan. Call only after the seller agrees. Calling again adds tasks; it does not erase earlier ones.",
     "input_schema": {"type": "object", "properties": {"actions": {"type": "array", "items": {"type": "object", "properties": {
         "title": {"type": "string"}, "owner": {"type": "string", "description": "Seller, or KAM (you)"},
         "due_in_days": {"type": "integer", "description": "0 to 90"}, "kpi": {"type": "string", "description": "measurable target"}},
         "required": ["title", "owner", "due_in_days", "kpi"]}}}, "required": ["actions"]}},
    {"name": "schedule_follow_up", "description": "Book a follow-up call to check KPIs, 1 to 60 days from today.",
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
SORRY = "Sorry, I didn't catch that. Could you say it again?"
# Spoken while the first tool of a turn runs, if Claude didn't say anything itself: (English, Hinglish)
FILLERS = {
    "get_seller_metrics": ("Sure, let me pull up your account.", "Ek second, aapka account dekhte hain."),
    "diagnose": ("Sure, let me pull up your account.", "Ek second, aapka account dekhte hain."),
    "raise_restock_alert": ("On it, setting that up now.", "Theek hai, abhi set kar dete hain."),
    "create_action_plan": ("On it, setting that up now.", "Theek hai, abhi set kar dete hain."),
}
# Common Hindi words written in English letters; two or more means the seller is speaking Hinglish
HINGLISH = {"hai", "hain", "kya", "kyun", "mera", "meri", "mere", "nahi", "nahin", "bhai", "kaise", "gaya", "gayi",
            "hua", "karo", "karna", "haan", "ji", "aap", "aapka", "mujhe", "kuch", "bahut", "sab", "theek", "abhi"}
SESSIONS = {}  # in-memory, single process; move to Redis if it ever runs multi-instance
SESSION_IDLE_SECONDS = 2 * 60 * 60  # forget calls idle for 2 hours


def is_hinglish(text):
    return len(set(re.findall(r"[a-z]+", text.lower())) & HINGLISH) >= 2


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
    if not user_text.strip():  # nothing heard: ask again without calling the model
        yield {"type": "reply", "text": SORRY, "plan": session["plan"]}
        return
    hinglish = is_hinglish(user_text)
    start = len(session["messages"])
    session["messages"].append({"role": "user", "content": user_text})
    spoke = False
    for _ in range(8):  # cap tool rounds per turn
        resp = client.messages.create(
            model=MODEL, max_tokens=2000, system=SYSTEM_PROMPT, tools=TOOLS,
            messages=session["messages"], output_config={"effort": "low"},
        )
        session["messages"].append({"role": "assistant", "content": resp.content})
        text = " ".join(b.text for b in resp.content if b.type == "text").strip()
        if resp.stop_reason in ("max_tokens", "refusal"):
            # Cut off or declined: a half-finished tool call would break every later turn, so undo this turn.
            del session["messages"][start:]
            yield {"type": "reply", "text": SORRY, "plan": session["plan"]}
            return
        if resp.stop_reason != "tool_use":
            yield {"type": "reply", "text": text or SORRY, "plan": session["plan"]}
            return
        if not text and not spoke:  # nothing said yet this turn: acknowledge so the seller isn't left in silence
            filler = FILLERS.get(next(b.name for b in resp.content if b.type == "tool_use"), ("", ""))
            text = filler[1] if hinglish else filler[0]
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


def allowed(code):
    """If ACCESS_CODE is set, every API call must send it (the page reads it from ?code= in the link)."""
    return not ACCESS_CODE or code == ACCESS_CODE


@app.post("/chat")
def chat(body: Chat, x_access_code: str = Header("")):
    """Streams one JSON object per line (NDJSON): session id first, then the events from agent_turn."""
    if not allowed(x_access_code):
        return Response(status_code=401)
    now = time.time()
    for old in [k for k, v in SESSIONS.items() if now - v["seen"] > SESSION_IDLE_SECONDS]:
        del SESSIONS[old]
    sid = body.session_id or str(uuid.uuid4())
    session = SESSIONS.setdefault(sid, {"messages": [], "plan": {}})
    session["seen"] = now

    def stream():
        n = len(session["messages"])
        yield json.dumps({"type": "session", "session_id": sid, "seller": SELLER["seller"]}) + "\n"
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
def tts(body: TTS, x_access_code: str = Header("")):
    """ElevenLabs if a key is set; otherwise 204 and the browser uses its own voice."""
    if not allowed(x_access_code):
        return Response(status_code=401)
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key or not body.text.strip():
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


def elevenlabs_transcribe(audio, content_type, key):
    """Sends the recorded audio to ElevenLabs Scribe and returns the text."""
    boundary = uuid.uuid4().hex
    model = os.environ.get("ELEVENLABS_STT_MODEL", "scribe_v1")
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="model_id"\r\n\r\n{model}\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="speech"\r\n'
            f'Content-Type: {content_type}\r\n\r\n').encode() + audio + f'\r\n--{boundary}--\r\n'.encode()
    req = urllib.request.Request("https://api.elevenlabs.io/v1/speech-to-text", data=body, headers={
        "xi-api-key": key, "Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r).get("text", "").strip()


@app.post("/stt")
async def stt(request: Request, x_access_code: str = Header("")):
    """More accurate speech-to-text. The page records each utterance and sends the audio here.
    Returns {"text": ...}, or 204 so the page keeps the browser's own transcript."""
    if not allowed(x_access_code):
        return Response(status_code=401)
    key = os.environ.get("ELEVENLABS_API_KEY")
    audio = await request.body()
    if not key or not audio or len(audio) > 5_000_000:  # 5 MB is minutes of speech; one turn is far less
        return Response(status_code=204)
    try:
        text = await run_in_threadpool(elevenlabs_transcribe, audio, request.headers.get("content-type", "audio/webm"), key)
    except Exception:
        return Response(status_code=204)
    return {"text": text} if text else Response(status_code=204)


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
        assert d["issues"][0]["issue"] == "Stock-outs on best sellers" and d["not_the_cause"]

        # Other scenarios: the diagnosis must follow the data, not the original story
        import copy

        def variant(last=None, this=None, detail=None):
            v = copy.deepcopy(SELLER)
            v["last_month"].update(last or {}); v["this_month"].update(this or {})
            if detail is not None:
                v["detail"] = detail
            return diagnose(v)

        flat = {"orders": 400, "sales": 200000, "oos_products": 5, "cancellation_rate": 0.08}
        no_detail = {"newly_oos_skus": [], "other_skus_orders": {"last_month": 400, "this_month": 400}}
        v = variant(this={**flat, "avg_price": 400, "sales": 160000}, detail=no_detail)  # price cut only
        assert v["headline"].startswith("Price problem") and v["issues"][0]["issue"] == "Lower selling price", v
        assert v["issues"][0]["revenue_lost_inr"] == 40000
        v = variant(this={"orders": 450, "sales": 225000, "oos_products": 5, "cancellation_rate": 0.08}, detail=no_detail)
        assert v["headline"].startswith("Sales did not drop") and v["root_cause"] == "No clear cause in this data."
        v = variant(this={**flat, "cancellation_rate": 0.30}, detail={})  # cancellations only, no detail at all
        assert [i["issue"] for i in v["issues"]] == ["More cancellations"]
        v = variant(this={"orders": 300, "sales": 165000, "avg_price": 550, "oos_products": 5, "cancellation_rate": 0.08},
                    detail={"newly_oos_skus": [], "other_skus_orders": {"last_month": 400, "this_month": 300}})
        assert "Higher price may be costing orders" in [i["issue"] for i in v["issues"]]
        assert "Lower visibility" in [i["issue"] for i in v["issues"]]
        v = variant(last={"orders": 0, "sales": 0, "avg_price": 0})  # brand-new seller: nothing to compare
        assert v["sales_change_pct"] is None and v["headline"].startswith("Sales did not drop")

        assert {t["name"] for t in TOOLS} == set(TOOL_FUNCS)
        s = {"plan": {}}
        r = TOOL_FUNCS["raise_restock_alert"](s, {"sku_ids": ["HD-101", "NOPE"]})
        assert r["alerts_raised"] == 1 and r["unknown"] == ["NOPE"] and r["suppliers_notified"] == ["Jaipur Textiles"]
        r = TOOL_FUNCS["create_action_plan"](s, {"actions": [{"title": "Restock", "owner": "Seller", "due_in_days": 7, "kpi": "OOS < 5"}]})
        assert r["added"] == 1 and s["plan"]["tasks"][0]["due"] == (date.today() + timedelta(days=7)).strftime("%a %d %b")
        TOOL_FUNCS["create_action_plan"](s, {"actions": [{"title": "Low-stock alerts", "owner": "Seller", "due_in_days": 2, "kpi": "on"}]})
        assert [t["title"] for t in s["plan"]["tasks"]] == ["Restock", "Low-stock alerts"]  # added, not replaced
        TOOL_FUNCS["raise_restock_alert"](s, {"sku_ids": ["HD-107"]})
        assert len(s["plan"]["restock_alerts"]) == 2  # added to the first alert
        for bad in ({"days": -5, "kpis": []}, {"days": 365, "kpis": []}):
            try:
                TOOL_FUNCS["schedule_follow_up"](s, bad); raise AssertionError("bad follow-up accepted")
            except ValueError:
                pass
        assert is_hinglish("Bhai mera sales bahut gir gaya hai") and not is_hinglish("My sales dropped, can you help?")
        r = TOOL_FUNCS["schedule_follow_up"](s, {"days": 7, "kpis": ["OOS < 5"]})
        assert r["booked"] and "11:00 AM" in s["plan"]["follow_up"]["when"]
        print("self-check OK:", d["headline"])
    else:
        # Local by default. For a public deploy: HOST=0.0.0.0, PORT from the platform, and set ACCESS_CODE.
        uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 8000)))
