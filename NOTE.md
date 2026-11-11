# Mini AI Voice KAM: design note

**Idea.** Kai is a Key Account Manager that owns the seller's problem, not a Q&A bot. It pulls the data itself, finds the cause, agrees a plan and then acts: it raises supplier restock alerts, creates dated tasks with owners and KPIs, and books a follow-up call. Each tool call shows on screen as it runs, and the call ends with a spoken summary and an action-plan card.

## Stack
| Layer | Choice | Why |
|---|---|---|
| Speech-to-text | ElevenLabs Scribe, with the browser's Web Speech API for live words and end-of-turn detection | The browser alone misheard Indian names; Scribe gets them right, and the browser is the fallback |
| Model | Claude Haiku 5.5 with tool use | Fast enough for voice; one env var switches to Sonnet 5.5 |
| Text-to-speech | ElevenLabs Flash v2.5, browser voice as fallback | Natural voice that never goes silent |
| App | FastAPI backend + one HTML page | Keys stay on the server |

## Workflow
```
mic → browser STT (live) + Scribe (/stt, accurate) → /chat → Claude ⇄ tools (loop until it answers) → /tts → speaker → listen again
         tools: get_seller_metrics · diagnose · raise_restock_alert · create_action_plan · schedule_follow_up
```
`/chat` streams each step to the browser as it happens. The seller hears "let me pull up your account" and sees each tool run while the model is still working, so there is no dead air. Kai listens again as soon as it stops speaking, and the ✋ button interrupts it.

## Prompt design (`prompt.md`)
A call script: look at the data before talking → one question to confirm the cause → three actions tied to numbers → get agreement → act with tools → spoken summary. Voice rules: word limits per turn, no lists or SKU codes, amounts said the Indian way, Hinglish if the seller uses it. Hard rule: use only numbers returned by tools.

## Diagnosis (`diagnose()` is plain Python; the model never does arithmetic)
It checks four causes (stock-outs, pricing, cancellations, visibility), puts a rupee value on each, and ranks them by revenue lost, so it works on any seller's numbers. For this seller:
1. Sales and orders both −32.5%, average price flat at ₹500 → **volume problem, not pricing**.
2. The 13 newly out-of-stock products fell from 150 orders to 20. That loss of 130 is **the whole drop** → **root cause: stock-outs on best sellers**.
3. Cancellations rose 8% → 14%; "item unavailable" went from 6 to 22 → **stock-outs drive the cancellations**.
4. Search impressions are down 15% → **visibility risk** that compounds next month.

Actions: restock the top three products and alert their suppliers; turn on low-stock alerts so new orders aren't cancelled; once restocked, run sponsored listings to win ranking back. The follow-up checks cancellation rate under 10% and out-of-stock under 5.

## Assumptions (added on top of the assignment's table)
- 60 products in the catalogue; 5 were already out of stock, 13 are new this month. Product names, suppliers and per-product orders are invented.
- Orders are gross (before cancellations). Cancellation reasons and search impressions are illustrative.
- Tools are mocks kept in memory for the call; nothing is sent anywhere.

## What I'd build next
Real seller APIs behind the same tools. **Proactive outbound calls** when stock-outs or cancellations cross a threshold, before sales fall. Streaming speech both ways for sub-second replies and voice barge-in. Hindi voices. A follow-up call that re-runs `diagnose()` and reports whether each KPI was hit, so impact is measured.
