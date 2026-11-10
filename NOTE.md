# Mini AI Voice KAM: design note

**Idea.** Not a Q&A bot: Kai is a Key Account Manager that owns the seller's problem. It pulls the data itself, works out the cause, agrees a plan with the seller and then acts: it raises supplier restock alerts, creates owned and dated tasks with KPIs, and books a follow-up call to check them. Every tool call shows on screen the moment it runs, and the call ends with a spoken summary and an action-plan card.

## Stack
| Layer | Choice | Why |
|---|---|---|
| Speech-to-text | Browser Web Speech API (`en-IN`, interim results) | Zero setup, low latency, handles Indian English |
| Brain | Claude Haiku 5.5 (Anthropic API) with tool use, low effort | Fast enough for voice turns; switch to Sonnet 5.5 with one env var |
| Tools | Plain Python functions in `server.py` | Easy to read, easy to swap for real seller APIs |
| Text-to-speech | ElevenLabs Flash v2.5 if a key is set, else the best browser voice | Natural voice, with a fallback that always works |
| App | FastAPI backend (holds keys, runs tools, streams events) + one HTML page | The API key never reaches the browser |

## Workflow
```
mic → Web Speech STT → POST /chat → Claude ⇄ tools (loop until it replies) → reply text → /tts → speaker → listen again
                                         │
                       get_seller_metrics · diagnose · raise_restock_alert · create_action_plan · schedule_follow_up
                                         │
              each step is streamed to the browser as one JSON line → live activity panel and action-plan card
```
- **Streaming:** `/chat` sends events as they happen (`say`, `tool`, `reply`). The seller hears "let me pull up your account" and sees each tool run while Claude is still working, so there is no dead air.
- **Turn-taking** is automatic: Kai listens again when it finishes speaking. Clicking ✋ while it speaks interrupts it.
- The greeting and the short "working on it" lines are fixed strings, so they cost no model call and no wait.

## Prompt design (`prompt.md`)
A call script, not a persona blurb: **look at the data before talking** → one question to confirm the cause → three actions tied to numbers → get agreement → act with tools → spoken summary. Voice rules: word limits per turn, no lists or SKU codes, amounts said the Indian way ("1 lakh 35 thousand"), reply in Hinglish if the seller does. Hard rule: **use only numbers returned by tools**.

## Diagnosis logic (deterministic `diagnose()`, the LLM never does the arithmetic)
1. Sales −32.5% and orders −32.5% with average price flat at ₹500 → **a volume problem, not pricing**.
2. The 13 newly out-of-stock SKUs fell from 150 orders to 20, a loss of 130 orders, which is **100% of the drop**. In-stock SKUs held at 250. → **Root cause: stock-outs on best sellers.**
3. Cancellations rose 8% → 14% (32 → 38). "Item unavailable" went from 6 to 22 → **the stock-outs are driving the cancellations.**
4. Search impressions are down 15% → **visibility risk**: stock-outs and cancellations hurt ranking, which compounds next month.

Recommended actions: restock the top SKUs (bedsheets, dinner set, curtains, mostly from one supplier) with supplier alerts; mark low-stock items unavailable or turn on low-stock alerts so new orders aren't cancelled; once restocked, boost visibility (deals or sponsored listings) to win ranking back. The follow-up checks cancellation rate under 10% and out-of-stock under 5 products.

## Assumptions (mock data added on top of the brief's table)
- The catalogue has 60 SKUs. 5 were out of stock last month as well; 13 new stock-outs this month (SKU names, suppliers and per-SKU orders are invented).
- Orders are **gross**, counted before cancellations; cancellation rate = cancelled ÷ orders.
- Cancellation reasons and search impressions are illustrative.
- Tools are mocks: alerts, tasks and follow-ups are kept in memory for the length of the call; nothing is sent anywhere.

## What I'd build next
Real seller APIs (orders, inventory, returns) behind the same tools. **Proactive outbound calls** when stock-outs or cancellations cross a threshold, before sales fall. Streaming speech both ways (Deepgram STT, token-by-token TTS) for sub-second replies and true voice barge-in. Hindi and Hinglish voices. Closing the loop: the follow-up call re-runs `diagnose()` and reports whether each KPI was hit, so impact is measured, not assumed.
