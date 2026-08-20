> **SUPERSEDED — 2026-08-20**
>
> Uses `C:\ayurveda` paths that exist on no machine, and a two-terminal Windows run flow. The stack now runs as systemd units.
>
> Production moved to the Ubuntu VM `10.1.30.37` on 19 Aug 2026.
> The authoritative description is [INFRASTRUCTURE.md](../INFRASTRUCTURE.md).
> Everything below is kept for history and may be wrong.

# Project kaise chalayein

Har baar bas **2 terminal** chahiye. Dono khule rakhne hain.

---

## 🖥️ Terminal 1 — Website (Dashboard)

PowerShell kholo aur ye 2 line paste karo:

```powershell
cd C:\ayurveda\apps\app
npx next dev -p 3000
```

Wait karo jab tak ye na dikhe:

```
✓ Ready in 2.5s
- Local:  http://localhost:3000
```

> ⚠️ Is window ko **band mat karna**. Minimize kar do.

---

## 🖥️ Terminal 2 — AI Chatbot (Python)

**Naya** PowerShell kholo (pehla band mat karo):

```powershell
cd C:\ayurveda\backend-python
.\.venv\Scripts\python.exe server.py
```

Wait karo jab tak ye na dikhe:

```
Warm-up complete — answers will be fast now.
Uvicorn running on http://0.0.0.0:4000
```

> ⚠️ Ye window bhi **band mat karna**.

---

## 🌐 Browser

Chrome mein kholo:

### **http://localhost:3000**

Bas. Login karo aur **Chat** par jaao.

---

## ⚠️ 3 zaroori baatein

1. **Hamesha capital `C:`** likhna → `C:\ayurveda` ✅ , `c:\ayurveda` ❌
   Chhote `c` se website crash ho jaati hai (Windows ka bug hai).

2. **Dono terminal khule rakhna** — band karoge to app band ho jaayegi.

3. **Convex ka kuch nahi karna** — wo cloud par khud chal raha hai, 24/7.

---

## 🛑 Band kaise karein

Har terminal mein `Ctrl + C` dabao, phir window band kar do. Kuch nahi khoyega —
saara data (users, chats, passwords) Convex cloud mein safe hai.

---

## 🆘 Problem aaye to

| Problem | Solution |
|---|---|
| `EADDRINUSE` / `port already in use` | Purana process chal raha hai. Ye chalao: `Get-Process node,python \| Stop-Process -Force` phir dobara start karo |
| Page **blank / white** aa raha hai | `c:` chhota likha tha. Terminal band karo, cache saaf karo: `Remove-Item -Recurse -Force C:\ayurveda\apps\app\.next` phir **capital `C:`** se start karo |
| Chat mein *"Could not reach the AI backend"* | Terminal 2 (Python) chalu nahi hai |
| `npx` / `node` not found | Node.js install nahi hai. `winget install OpenJS.NodeJS.LTS` |
| Login code email par nahi aaya | Email sirf **akshat@networkershome.com** par jaati hai (Resend free plan ki limit) |

---

## 🔧 Kab kya extra karna padta hai

Ye **rozana nahi** karna — sirf in cases mein:

**Backend ka code badla (`packages/backend/convex/`)**
```powershell
cd C:\ayurveda\packages\backend
npx convex dev --once
```

**Knowledge notes add ya edit kiye (`backend-python/data/knowledge/*.md`)**
```powershell
cd C:\ayurveda\backend-python
.\.venv\Scripts\python.exe scripts\ingest_knowledge.py
```
Phir Terminal 2 restart kar dena. (Ye dobara chalana safe hai — duplicate nahi bante.)

**Nayi library install ki**
```powershell
cd C:\ayurveda
bun install
```

---

## 🧪 Sab theek hai ya nahi, check karna ho to

```powershell
# Conversation engine (30 tests)
cd C:\ayurveda\backend-python
.\.venv\Scripts\python.exe tests\test_conversation.py

# Bad-JSON handling (10 tests)
.\.venv\Scripts\python.exe tests\test_repair.py
```

Browser wale tests ke liye dono server chalu hone chahiye:

```powershell
cd C:\ayurveda\e2e
node consult-local.js    # consultation flow, 14 tests
node auth-local.js       # login/signup, 20 tests
```

*(Auth tests ke liye ek teesra terminal chahiye: `cd C:\ayurveda\packages\backend` phir
`npx convex logs > C:\temp\logs.txt`, aur `$env:E2E_LOG_FILE` usi path par set karna.)*
