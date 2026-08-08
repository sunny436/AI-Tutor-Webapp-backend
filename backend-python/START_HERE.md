# START HERE — how to run it (simple)

There are two parts: the **Python AI brain** (this `backend-python` folder) and
the **dashboard** (the Convex template around it). Do the quick test first.

---

## ✅ Step 1 — Install Python (once)
Download from https://python.org and during install tick **"Add Python to PATH"**.

## ✅ Step 2 — Get a free Groq key (once)
Go to https://console.groq.com → sign in → **API Keys** → create a key (copy it).

## ✅ Step 3 — Put your key in the settings file
Open the file **`.env`** in this folder. Find this line:
```
GROQ_API_KEY=PASTE_YOUR_GROQ_KEY_HERE
```
Replace `PASTE_YOUR_GROQ_KEY_HERE` with your real Groq key. Save the file.
(The other secrets are already filled in for you.)

## ✅ Step 4 — Quick test the AI (no dashboard needed)
Double-click **`try_it.bat`**.
The first time it installs everything (a few minutes), then asks you to type a
problem. You should get an Ayurveda/Yoga answer. 🎉

---

## Next — run the full app with the dashboard
When the quick test works, run the whole thing:

1. Double-click **`run_backend.bat`** → the AI backend runs at http://localhost:4000
   (leave this window open).
2. Follow the dashboard + Convex steps your assistant will guide you through
   (Convex login, ngrok tunnel, and `bun dev:app`).

If anything shows a red error, copy the text and send it to your assistant.
