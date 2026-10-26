# Known limitations

> Verified at commit `0e33ec0` (2026-10-26). Production states are as reported by `bun run status` and the
> release session on the dates given; they live in the server's settings, not in git.

These are the gaps that are true today, each with where it shows. A limitation that was chosen on purpose links
to its reason in [decisions.md](decisions.md). Planned work is in [ROADMAP.md](../ROADMAP.md).

## Contents

- [For students](#for-students)
- [Files](#files)
- [Production and operations](#production-and-operations)
- [Development and testing](#development-and-testing)
- [Platform](#platform)

## For students

| Limitation | Where it shows |
|---|---|
| **Voice mode is English only.** It is offered only when the tutor's language is English or unset | `app/voice/`; OllaLink's speech has no Hindi |
| **Textbook search covers NCERT Classes 6–12 only**, and needs the separate NCERT Knowledge Service. Without the service, answers come without textbook sources | `app/rag/ncert.py` (`SERVED_CLASSES`) |
| **Tests in the chat exist only for what the question bank covers** | `app/qbank/chat_tests.py` |
| **The tutor can be wrong.** Its own fill-in-the-blank exercises are marked, but never counted as evidence of what a student knows | Help > "Can the tutor be wrong?"; [CLAUDE.md](../CLAUDE.md), "Backend internals" |
| **If the model fails partway through a reply, that reply ends with an error.** The fallback model is used only before the first word | `app/llm/fallback.py`; [decisions.md](decisions.md#one-model-call-per-turn-and-the-fallback-only-before-the-first-token) |
| **Learning days follow India time** for every student | `app/progress/learning.py` (`Asia/Kolkata`) |
| **Dictation depends on the browser's speech recognition.** Without it, there is no dictation button | `features/chat/dictation.ts` |
| **On a phone, the year's activity calendar scrolls sideways** | Settings > Learning & Streak ("Scroll sideways to see the whole year") |
| **The teaching defaults are off** by default | `TUTOR_TEACHING_POLICY` |
| **The adaptive CAPTCHA isn't configured in production** (2026-10-26) | `TURNSTILE_*` unset |
| **Homework Helper and Summarizer are sample-data previews** and never appear in production | `PREVIEW_FEATURES` |

## Files

| Limitation | Where it shows |
|---|---|
| 100 MB per student. Per file: PDF, Word and PowerPoint 25 MB; Excel and images 10 MB; CSV and text 2 MB | The File Library page |
| At most 5 attachments per message. A turn reads the conversation's 5 most recently attached files, up to 4,000 passages in total | `app/files/service.py` (`MAX_ATTACHMENTS`, `SCOPE_FILES`, `SCOPE_CHUNKS`) |
| Uploads stop when PadhAI's own tables reach 3 GiB, or the disk has less than 5 GB free | `app/files/service.py` (`check_capacity`) |
| Images and scanned pages need Tesseract (English and Hindi) on the server | `app/files/extract.py` |
| Files' bytes are stored in PostgreSQL, so the database grows with uploads | `user_file_blobs`; [decisions.md](decisions.md#files-bytes-live-in-postgresql) |

## Production and operations

| Limitation | Where it shows |
|---|---|
| **The jobs worker isn't enabled.** So nothing sends reminder emails (daily, streak, weekly summary) or forwards support requests by email, and the outbox redaction and the read-notification purge don't run. Sign-in codes and security emails are not affected: the API sends them directly | `JOBS_ENABLED`, `NOTIFICATIONS_MODE`; [deployment.md](deployment.md#jobs-worker) |
| **No fallback model is configured in production** (2026-10-26), so if the primary provider is down, replies fail until it is back | `LLM_FALLBACK_MODEL` unset; [operations.md](operations.md#runbooks) |
| **One host:** no staging environment, no replica, no load balancing. A host failure is an outage until restored | [INFRASTRUCTURE.md](../INFRASTRUCTURE.md), "Known limits" |
| **The API is one process**, and it tracks replies in flight in that process | `aichat-api.service`; `app/chat/streams.py` |
| **A deploy that restarts the API ends any reply being written at that moment**; it is saved as cancelled | [INFRASTRUCTURE.md](../INFRASTRUCTURE.md), "Known limits" |
| **The services run as root, and there is no alerting.** `bun run status` and `infra-check.sh` are run by hand | `deploy/systemd/`; [INFRASTRUCTURE.md](../INFRASTRUCTURE.md) |
| **Backups stay on the same host** unless copied off by hand, and they are kept for 7 days. A deleted account's data stays in the dumps taken before the deletion, until they rotate out | `deploy/backup.sh` (`KEEP_DAYS`) |
| **No metrics, tracing or backend error reporting.** Browser errors are reported only when `NEXT_PUBLIC_SENTRY_DSN` is set | [operations.md](operations.md#logs-and-what-they-contain) |

## Development and testing

| Limitation | Where it shows |
|---|---|
| **No Docker on the owner's PC** (the owner's rule), so the backend tests, the end-to-end suite and `bun run verify` run only in CI | [testing.md](testing.md) |
| **The local setup steps are verified by reading the code**, not by running them on that PC; macOS isn't verified at all | [beginner-guide.md](beginner-guide.md) |
| **The example env files leave settings out:** the web app's sign-in settings, the API's `AUTH_INTERNAL_TOKEN`, and the voice, study-time and question-bank settings | [environment-variables.md](environment-variables.md#what-the-example-files-list) |
| **`HOST` and `PORT` are declared in the API's settings, but never read.** uvicorn's flags decide | `app/settings.py`; `scripts/run.mjs` |
| **A CI job is red:** "Integration (end-to-end)" at `0e33ec0` (2026-10-26), after "Backend (lint, contract, tests)" on 2026-10-22 and 10-23. At `0e33ec0` it is one flaky WebKit Settings test (190 passed, 1 failed), not yet fixed | [testing.md](testing.md#known-baseline) |
| **The visual regression baselines were recorded on Windows**, so they are meant to run there | `e2e/visual-regression.e2e.ts` |
| **Fake embeddings only match shared words.** They prove the plumbing, not search quality | [rag.md](rag.md) |

## Platform

| Limitation | Where it shows |
|---|---|
| **The web app is the only client.** Native apps would need a published API and the changes listed in [architecture.md](architecture.md), "Clients" | `docs/architecture.md` |
| **The API has no public address.** Only the web app's server can reach it | [security.md](security.md) |
