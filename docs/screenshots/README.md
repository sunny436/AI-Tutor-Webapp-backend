# Screenshots

Real screenshots of PadhAI, taken from the live site on **2026-10-26** (05:11–05:19 UTC), when production ran
commit `0e33ec0`. They were taken while signed in as the owner's QA test account, not a student's. Every image
was checked by eye before it was added here.

## How they were made, and what was masked

They were taken by a scratch Playwright script, which is not part of the repository.

**What the script was allowed to do:**
- **Writes were blocked by default.** The script was allowed only to:
  - sign in and sign out;
  - ask three demo questions in two new chats;
  - run the read-only tutor preview;
  - delete its own demo chats.
- **Everything else was refused**, including study beats, Cloudflare's page beacon, saving settings and marking
  notifications read.
- **Clean-up afterwards:**
  - both demo chats were deleted, and the API confirmed both are gone (404);
  - the session was signed out, and the API then answered 401;
  - the saved session file was deleted.

**What was changed in the page before each capture:**
- The account's name, email and initial show as **Demo Student**, **student@example.com** and **D**.
- The titles of the account's other chats are **blurred**. File names would have been blurred too, but no file
  appears.
- **Dark mode** (`desktop/dark-mode.png`) was switched on in the page for the capture, with the same theme classes
  the theme control sets. The account's setting wasn't changed.
- **Study Activity's session card** loads from the page's first study beat, which is a write. So that one request
  was answered with the account's real state from the read-only `GET /api/v1/study/session`, and no study time was
  recorded.
- **Voice mode** was opened with the browser's fake microphone. Nothing was said, so it shows the listening state.

The streak, study minutes, practice topics and exam date are the QA account's own test data, not a real
student's.

## Desktop (1440 × 900, Chromium)

| Image | Page | What it shows |
|---|---|---|
| ![Sign in](desktop/sign-in.png) | `/login`, signed out | Sign in with Google, or email and password; "Email me a code instead"; "Create an account" |
| ![New chat](desktop/new-chat.png) | `/` | A new chat: the week's study greeting on one line and the composer. The sidebar has My Learning, File Library, Study Activity and recent chats. The header has the streak and the time left in the India learning day |
| ![Tutor answer](desktop/tutor-answer.png) | `/c/<id>` | An answer with numbered steps, KaTeX maths, an Answer card and NCERT textbook sources |
| ![Answer with a table](desktop/tutor-answer-table.png) | `/c/<id>` | A comparison table with citation chips, a Note card and sources |
| ![Dark mode](desktop/dark-mode.png) | `/c/<id>` | The same chat in the dark theme |
| ![My Learning](desktop/my-learning.png) | `/learning` | Today's plan with revisions due, today's test answers against the 5 that make a learning day, practice by chapter, and the exam date |
| ![Study Activity](desktop/study-activity.png) | `/study` | Starting a study session (subject and activity), then estimated study time against time in PadhAI over the last 7 days, the daily goal and the trend |
| ![File Library](desktop/file-library.png) | `/library` | Storage used out of 100 MB, the accepted file types and their size limits, and the empty state |
| ![Settings: AI Tutor](desktop/settings-ai-tutor.png) | `/settings/tutor` | Tone, answer length, how problems are answered, step-by-step, practice questions and more, each with "No preference" |
| ![Settings: Appearance](desktop/settings-appearance.png) | `/settings/appearance` | Theme, text size, high contrast, reduce motion and comfortable reading |
| ![Settings: Learning and Streak](desktop/settings-streak.png) | `/settings/streak` | Current and longest streak, today's learning, the year's activity calendar and the header toggle |
| ![Help](desktop/help.png) | `/help` | Help and FAQ by topic, with a link to contact support |

## Workflows (desktop)

| Image | What it shows |
|---|---|
| ![Streaming reply](workflows/streaming-reply.png) | A reply while it streams: the text so far with a cursor, and the composer's Stop button |
| ![Voice mode](workflows/voice-mode.png) | Voice mode over a chat: only the tutor's face, the state line ("Listening…") and three controls (back to the chat, microphone, end) |

## Phones

| Image | Device | What it shows |
|---|---|---|
| ![New chat on iPhone](mobile/new-chat.png) | iPhone 14 (WebKit) | A new chat; the greeting fits one line |
| ![Answer on iPhone](mobile/tutor-answer.png) | iPhone 14 (WebKit) | The end of an answer: a table, a Note card, sources, and Copy, Regenerate and feedback |
| ![Drawer](mobile/drawer.png) | Pixel 7 (Chromium) | The navigation drawer, with Rename and Delete visible on each chat |
| ![Settings](mobile/settings.png) | Pixel 7 (Chromium) | Settings as a list of sections |
| ![Streak calendar](mobile/streak-calendar.png) | Pixel 7 (Chromium) | Learning and Streak, with the "Scroll sideways to see the whole year" hint under the calendar |

## Tablet

| Image | Device | What it shows |
|---|---|---|
| ![iPad](tablet/chat-actions.png) | iPad Pro 11 (WebKit) | A new chat beside the sidebar. A touch screen has no hover, so each chat's Rename and Delete are always shown |

## Updating them

Take new screenshots only with the owner's approval, using the QA account, and keep the same rules:
- block writes by default;
- mask before every capture;
- delete what you created, then confirm it is gone;
- sign out and confirm the session no longer works;
- check every image by eye.

Keep the same file names, so the links in [README.md](../../README.md) and [features.md](../features.md) keep
working.
