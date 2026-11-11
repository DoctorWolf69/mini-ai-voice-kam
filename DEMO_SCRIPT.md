# Recording the demo

Target length: **1:30 to 1:55**. The assignment allows 1–2 minutes.

## Before you record (5 minutes)

1. **Server running.** In a terminal in this folder: `python server.py`. Leave it open.
2. **Browser.** Open http://127.0.0.1:8000 in **Chrome**. Close other tabs. Press F11 for full screen, then Ctrl + plus once (110% zoom) so the tool panel is readable in the video.
3. **No interruptions.** Turn on Do Not Disturb (Windows notification bell → Do not disturb) and mute your phone.
4. **Recorder settings** (one time):
   - Press **Win+G** to open Game Bar. In the **Capture** widget, click the mic icon so it shows **on** (otherwise only Kai is recorded, not you).
   - Settings → Gaming → Captures: set **Captured audio** to "Everything" or leave "Game" (the browser counts), and **Video quality** to "High".
5. **Test run (30 seconds).** Win+Alt+R, say "testing, one two", start a call so Kai greets you, Win+Alt+R to stop. Open `Videos\Captures` and play it: you should hear **both** your voice and Kai's. Delete the test.
6. **Practice call once** without recording, so you know the rhythm. Headphones are optional: the mic is off while Kai speaks.

## Recording

Click on the Chrome window first (Game Bar records the active window), then **Win+Alt+R** to start.

| # | What happens | What you say |
|---|---|---|
| 1 | Wait 2 seconds on the empty page, then press the green 📞. Kai greets you. | (nothing) |
| 2 | "Listening…" appears. | **"Hi Kai. My sales have dropped significantly this month. I don't understand why. Can you help me?"** |
| 3 | Kai says "let me pull up your account"; `get_seller_metrics` and `diagnose` appear in the panel. Kai explains: stock-outs, not pricing, and asks why items ran out. | **"Yes, my supplier Jaipur Textiles delayed the last shipment, and I didn't notice how many items had run out."** |
| 4 | Kai recommends three actions and asks "Shall I set this up for you?" | **"Yes, go ahead."** (clearer than "set it up", which can be misheard as "shut up") |
| 5 | `raise_restock_alert`, `create_action_plan`, `schedule_follow_up` appear; the action-plan card fills in. Kai gives the summary and says goodbye. | **"Thanks, Kai."** |
| 6 | Wait 3 seconds on the finished screen (plan card visible), then **Win+Alt+R** to stop. | (nothing) |

**Tips**
- Speak clearly at normal speed, then **pause**. Kai only sends your words after a short silence.
- If Kai asks something unexpected, answer in a few words ("yes", "Friday works") and carry on.
- If something goes wrong (Kai mishears, a long pause), stop and record again. Two or three takes is normal; keep the best one.
- Don't click anything while Kai is speaking; clicking ✋ interrupts it.

## After recording

1. Open the file in `Videos\Captures` and watch it once with sound.
2. If there's dead time at the start or end, trim it: right-click the file → Open with → **Clipchamp** (or Photos → Edit → Trim). Export at 1080p.
3. Save it in this folder as **`demo.mp4`**. It isn't committed to GitHub (it's in `.gitignore`); you'll attach it or share a Drive link in the email.
