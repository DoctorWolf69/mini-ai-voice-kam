# Mini AI Voice KAM

A browser voice bot that acts as a marketplace seller's Virtual Key Account Manager (KAM).

The seller calls and says "my sales dropped, I don't know why". Kai, the KAM, pulls the seller's data, works out the cause, agrees a plan, and then acts: it raises restock alerts to suppliers, creates dated tasks with owners and KPIs, books a follow-up call, and summarises everything out loud. Each tool call appears on screen as it runs.

Built for the "Mini AI Voice KAM" take-home assignment. All seller data is mock data.

## Run

```bash
pip install -r requirements.txt
cp .env.example .env      # add ANTHROPIC_API_KEY; ELEVENLABS_API_KEY (optional) needs Text to Speech and Speech to Text
python server.py
```

Open http://127.0.0.1:8000 in **Chrome or Edge**, press the green button, allow the microphone and say:

> "My sales have dropped significantly this month. I don't understand why. Can you help me?"

- The ✋ button interrupts Kai while it speaks, and ends the call while it listens.
- Kai replies in Hinglish if you speak Hinglish.
- `python server.py --check` runs the self-check on the diagnosis and tools (no API calls).

### Sharing a public link
Set `ACCESS_CODE` in `.env` (and `HOST=0.0.0.0`, plus `PORT` if the platform gives one). Share the link as `https://your-host/?code=YOUR_CODE`. Requests without the code are refused, so strangers can't spend your API credits.

## How it works

```
mic → Web Speech API (live words, end of turn) + /stt (ElevenLabs Scribe, accurate text) → POST /chat → Claude + tools → reply → /tts (ElevenLabs) → speaker
```

| File | What it is |
|---|---|
| `server.py` | FastAPI app: mock seller data, the five tools, the Claude tool loop, `/chat` (streams events), `/stt` and `/tts` |
| `prompt.md` | System prompt: call flow, rules for numbers, voice style |
| `index.html` | The whole UI: speech in and out, transcript, live tool panel, action-plan card |
| `NOTE.md` | One-page design note: models, workflow, diagnosis logic, assumptions, next steps |
| `DEMO_SCRIPT.md` | The seller's lines used for the screen recording |

## Tools the agent can call

| Tool | What it does |
|---|---|
| `get_seller_metrics` | Returns last month vs this month, plus per-product detail |
| `diagnose` | Plain Python that computes every change and ranks the issues. The model never does the arithmetic |
| `raise_restock_alert` | Sends (mock) restock alerts to suppliers for chosen products |
| `create_action_plan` | Creates tasks with owner, due date and target KPI |
| `schedule_follow_up` | Books a (mock) follow-up call to check the KPIs |

See [NOTE.md](NOTE.md) for the design decisions and assumptions.
