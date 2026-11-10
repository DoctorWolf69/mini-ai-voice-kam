# Recording script (aim for 1:30)

**Setup:** Chrome or Edge, full screen at http://127.0.0.1:8000, headphones (stops Kai hearing itself), quiet room. Record with Win+Alt+R (Game Bar captures mic and system audio) and stop with Win+Alt+R again. The file lands in `Videos\Captures`; move it here as `demo.mp4`.

Speak naturally. Kai may word things differently each time, so just answer what it asks. These are your lines:

1. Press 📞. Kai greets you.
2. **You:** "Hi. My sales have dropped significantly this month. I don't understand why. Can you help me?"
   → watch `get_seller_metrics` and `diagnose` appear in the panel. Kai says it's a stock problem, not pricing.
3. Kai asks why the items ran out. **You:** "Yes, my supplier Jaipur Textiles delayed the last shipment, and I didn't notice how many items had run out."
4. Kai suggests three actions and asks if it should set them up. **You:** "Yes, please set it up."
   → `raise_restock_alert`, `create_action_plan` and `schedule_follow_up` fire, and the action-plan card appears.
5. If Kai asks something else, answer briefly ("Friday works", "yes, go ahead").
6. Kai gives the spoken summary. **You:** "Thanks, Kai." End the call.

If it runs long, trim the silences at the start or end in the Photos or Clipchamp editor. Keep it under 2:00.
