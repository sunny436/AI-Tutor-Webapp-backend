# Features

> Verified at commit `0e33ec0` (2026-10-26) against the code. **Production states** come from `bun run status`
> (2026-10-26) and the release session's report (2026-10-26); they are settings in `api.env` and `web.env`, not
> code, and can change without a commit. Screenshots: [the gallery](screenshots/README.md).

**Status key:**
- **On**: works by default in the code.
- **Flag**: behind a setting; its production state is given.
- **Off in production**: built, but not switched on there.
- **Preview**: sample-data pages, only with `PREVIEW_FEATURES=1`, never in production.
- **Removed**: gone, listed so nobody looks for it.

## Learning with the tutor

| Feature | Status | What a student gets | Where |
|---|---|---|---|
| Chat with streamed answers | On | Ask anything about school subjects; the answer appears word by word, with Stop, Regenerate, Copy and thumbs up or down | `features/chat/`, `app/chat/`; [screenshot](screenshots/workflows/streaming-reply.png) |
| Rich answers | On | Tables, code, maths and chemistry (KaTeX with mhchem), study cards, diagrams, charts, graphs, flashcards, and citations to textbook pages | `features/markdown/`; [screenshot](screenshots/desktop/tutor-answer.png), [2](screenshots/desktop/tutor-answer-table.png) |
| NCERT textbook grounding | On when configured (configured in production) | Answers draw on the NCERT books for Classes 6–12, with the student's own class and subjects ranked first, and cite them | `app/rag/ncert.py`, [rag.md](rag.md) |
| Personalised tutor | On | Class, board, medium, goals, subjects and preferences (language, depth, pace, examples, tone and more) shape every answer. Settings > AI Tutor previews exactly what the tutor is told | `app/learning/tutor.py`, Settings; [screenshot](screenshots/desktop/settings-ai-tutor.png) |
| Study scope (JEV) | Flag `STUDY_SCOPE` (production: **on**, 2026-10-26) | The tutor keeps to learning; clearly unrelated requests get a short redirect | `app/intents/scope.py` |
| Intent router (JEV) | Flag `INTENT_ROUTER` (production: **on**, 2026-10-26) | Tailors each answer to the kind of help asked for (46 intents) | `app/intents/` |
| Attach your own files | On | PDF, Word, PowerPoint, Excel, CSV, text, Markdown and images (OCR in English and Hindi) can be attached to a chat; the tutor reads them and cites `[F1]` | `features/files/`, `app/files/`; [screenshot](screenshots/desktop/file-library.png) |
| Dictation | On (where the browser supports it) | Speak into the composer with the browser's own speech recognition; text is added to the draft, never sent by itself | `features/chat/dictation.ts` |
| Voice mode | Flag `VOICE_MODE` (production: **on**, 2026-10-26) | Talk with the tutor and hear the answer, with an animated face. English only, so it's offered when the tutor language is English or unset | `features/voice/`, `app/voice/`; [screenshot](screenshots/workflows/voice-mode.png) |
| Weekly study greeting | On | A fresh line above each new chat, from a weekly pool | `app/greetings/`; [screenshot](screenshots/desktop/new-chat.png), [2](screenshots/mobile/new-chat.png) |
| Teaching defaults | Flag `TUTOR_TEACHING_POLICY` (default off) | Direct answers when asked, mistakes diagnosed before correction, one hint at a time | `app/chat/teaching.py` |

## Practice and progress

| Feature | Status | What a student gets | Where |
|---|---|---|---|
| Tests from the question bank | On (`QUESTION_BANK_TESTS`) | "Test me on…" in the chat gives stored questions (approved or awaiting review, never drafts), never invented ones, marked by the database | `app/qbank/chat_tests.py`, [question_bank.md](question_bank.md) |
| Adaptive tests | On (`ADAPTIVE_CHAT_TESTS`) | Each next question is chosen from the previous answer | `app/qbank/selection.py` |
| My Learning | On | Today's plan, a subject → chapter → topic picker, revisions due, mastery estimates, mistakes and recent tests, all from the practice record | `/learning`, `features/my-learning/`; [screenshot](screenshots/desktop/my-learning.png) |
| Learning streak | On | Consecutive India days of real learning, a countdown to the day's end, and celebrations for new streaks and milestones | `features/streak/`, `app/progress/learning.py`; [screenshot](screenshots/desktop/settings-streak.png), [2](screenshots/mobile/streak-calendar.png) |
| Active time and goals | On | Minutes PadhAI was open and used, against daily and weekly goals (Settings > Progress & Goals) | `app/progress/` |
| Study Activity | On | Start, pause and end study sessions; estimated active, idle and paused time by day, subject and chapter | `/study`, `features/study/`, `app/study/`; [screenshot](screenshots/desktop/study-activity.png) |

## Account, settings and help

| Feature | Status | What a student gets | Where |
|---|---|---|---|
| Sign up and sign in | On | Email first (a code, then a password); sign in by password or email code; password reset by code | `lib/auth/`; [screenshot](screenshots/desktop/sign-in.png) |
| Google sign-in | On when configured (configured in production, 2026-10-26) | "Continue with Google" | `GOOGLE_CLIENT_ID` and secret |
| Two-step sign-in | On | An authenticator app and recovery codes, asked for at every way in | Settings > Privacy & Security |
| Adaptive CAPTCHA | Flag: Turnstile keys (production: **not configured**, 2026-10-26) | A challenge only when an address is being hammered | `lib/auth/config.ts` |
| Breached-password check | On | Passwords seen in a breach are refused | `lib/auth/protection.ts` |
| Devices and sign-out | On | The list of signed-in devices (masked addresses); sign out one or all others | Settings > Privacy & Security |
| Profile, email change, account deletion | On | Photo, name, time zone; changing the email by code; deleting the account and all its data | Settings > Profile, Privacy & Security |
| Settings workspace | On | 13 sections, with search, versioned saves and no lost edits | `features/settings/`; [screenshot](screenshots/mobile/settings.png) |
| Appearance and accessibility | On | Theme, text size, high contrast, reduce motion, reading comfort, show or hide the streak, the same on every device | Settings > Appearance & Accessibility; [screenshot](screenshots/desktop/settings-appearance.png), [2](screenshots/desktop/dark-mode.png) |
| Help and support | On | Help pages; support requests are stored and forwarded to the team | `/help`, Settings > Help & Support; [screenshot](screenshots/desktop/help.png) |

## Notifications

| Feature | Status | Notes |
|---|---|---|
| The bell (in-app) | On | Notifications with Read all and Clear all, kept by the server |
| Sign-in codes and security emails | On | Codes, sign-in alerts, password and two-step notices, and the welcome email are sent by the API right after the event, as branded HTML with a plain-text part |
| Reminder emails (daily, streak, weekly summary) | **Off in production** | They need the jobs worker and `NOTIFICATIONS_MODE`, neither enabled ([deployment.md, "Jobs worker"](deployment.md#jobs-worker)) |
| Support request forwarding by email | **Off in production** | Requests are stored; forwarding goes through the outbox, which only the jobs worker sends |

## Preview and removed

| Feature | Status |
|---|---|
| Homework Helper, Summarizer (`/homework`, `/summarizer`) | **Preview**: sample data only, `PREVIEW_FEATURES=1`, never in production |
| My Courses, Course Creator, the Flashcards page | **Removed** when My Learning replaced them. The chat's own `flashcards` block stays |

## Platforms

- **Web:** desktop, tablet and phone layouts. Below 768 px navigation is a drawer, and from 768 px it is a sidebar
  rail. See the [phone drawer](screenshots/mobile/drawer.png) and the [tablet](screenshots/tablet/chat-actions.png),
  where touch screens always show each chat's Rename and Delete.
- **Accessibility:** checked by axe in the end-to-end tests, keyboard-reachable, reduced-motion aware.
- **Other clients:** the API is ready for future native clients ([architecture.md, "Clients"](architecture.md#clients-web-first-not-web-only)),
  but no other client exists.
