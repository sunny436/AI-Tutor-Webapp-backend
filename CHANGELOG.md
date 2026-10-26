# Changelog

These are the milestones, newest first, each with the commit that brought it. Every commit is a release of both
halves, and `git log` is the complete, authoritative record. The dates are commit dates. A milestone isn't
necessarily live from that date: production runs what was last deployed (`bun run status`).

## 2026-10

| Date | Commit | Milestone |
|---|---|---|
| 2026-10-26 | (this file) | Documentation: a docs hub, a beginner guide, architecture, API reference, data model, security, AI architecture, environment variables, operations, troubleshooting, decisions, known limitations, a rebuild prompt and real screenshots; a proprietary licence with third-party notices |
| 2026-10-26 | `0e33ec0` | Voice mode: only the tutor on screen; a 0.6 s pause ends the question; a chime when it is sent; speech starts sooner |
| 2026-10-23 | `99d812c` | Voice mode: talk with the tutor (OllaLink speech, English only), behind `VOICE_MODE` (off by default) |
| 2026-10-23 | `f5d52ab`, `bd97bf7`, `eedcb67` | Faster on slow phones and with long chats |
| 2026-10-23 | `3b927c5` | Chat layout: replies fill a readable conversation column |
| 2026-10-23 | `de74ba3` | Study scope: a message in a chat with a test or an exercise is never turned away |
| 2026-10-22 | `391d732` | Learning engine, My Learning, the intent router and the study scope filter (router and scope off by default) |
| 2026-10-22 | `66a989d`, `a125a58`, `418c935`, `f47162f` | Responsive fixes: actions visible on touch tablets, focusable equations, 16 px fields on phones, a one-line greeting, the calendar's scroll hint |
| 2026-10-22 | `b427146` | The greeting and the header's status, polished |
| 2026-10-19 | `670d8c8` | Branded HTML account emails |
| 2026-10-16 | `86392b1` | Tests in the chat come from the question bank: the tutor names a chapter, the server sets stored questions |
| 2026-10-16 | `412a393` | The question bank's content: CBSE multiple-choice questions for Classes 6–12 |
| 2026-10-15 | `9f895ee` | The question bank: stored questions, served by SQL only |
| 2026-10-15 | `1cdcb67` | Backups: PadhAI's own data only, without the NCERT service's schema |
| 2026-10-15 | `b38ae30` | Study time: sessions with estimated active, idle and paused time; Study Activity; Settings > Study Tracking |
| 2026-10-14 | `73cd388` | Streak celebrations |
| 2026-10-14 | `3671a4f` | NCERT textbooks from the NCERT Knowledge Service, behind `NCERT_KB_*` |
| 2026-10-13 | `a37b4e9` | Teaching defaults behind `TUTOR_TEACHING_POLICY` (off by default) |
| 2026-10-12 | `649cddc` | Production moved to a new host; the model reached through Ollima's public gateway |
| 2026-10-02 | `d32d492` | Security: two-step sign-in, an adaptive CAPTCHA, the breached-password check, Next.js 15 |
| 2026-10-01 | `6be7ce8` | Sign-in on Better Auth: email-first sign-up, codes, passwords, Google-ready; the API checks every session |
| 2026-10-01 | `26c1335`, `6c6ba47` | Practice tests the server keeps, and a tutor that knows the student's finished tests and exercises |

## 2026-09

| Date | Commit | Milestone |
|---|---|---|
| 2026-09-30 | `29558f4` | Rich replies: study cards, diagrams, charts, chemistry, citations, practice widgets |
| 2026-09-30 | `4acf18c` | The File Library, chat attachments and dictation |
| 2026-09-29 | `2923b70` | The Noto Sans type system, and the owner's hard rules for production and testing |
| 2026-09-29 | `7391c75` | The tutor receives the academic year, study time and how the student is doing |
| 2026-09-29 | `369cd9e` | Chats named in a few words; the header shows the chat's name |
| 2026-09-29 | none | The owner removed the legacy stack from production by hand ([docs/production-migration.md](docs/production-migration.md)) |
| 2026-09-28 | `b845917` | New chat: a weekly study greeting and one centred composer; Settings as product cards |
| 2026-09-28 | `173d8dc` | Deploys: push `main` to production's Git repository, rebuild and restart only what changed |
| 2026-09-28 | `d1bdf9f` | GitHub Actions is no longer a deploy dependency (CI is advisory) |
| 2026-09-27 | `a911777` | The learning streak and the notification bell |
| 2026-09-26 | `70dbf3b` | Settings: Progress, Help and Support, and the real streak |
| 2026-09-24 | `1b40e0f` | One deploy command, one release, one rollback point |
| 2026-09-24 | `85b7abb` | The web app imported into `frontend/` with its full history |
| 2026-09-23 | `15fa103` | Every chat turn runs through a LangGraph retrieval graph |
| 2026-09-23 | `68ebd27` | The PostgreSQL schema and migrations, with pgvector |
| 2026-09-23 | `768e156`, `f3c2f30` | The FastAPI backend replaces the Ayurveda chatbot, which is kept at the tag `ayurveda-baseline` |

## 2026-08

| Date | Commit | Milestone |
|---|---|---|
| 2026-08-18 | `bb0ae5f` | The web app split out into its own repository (imported back into `frontend/` on 2026-09-24) |
| 2026-08-08 | `1e744df` | The project's first upload, built on the "v1" starter kit ([THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)) |
