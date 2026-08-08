# Knowledge file format

Every note in `data/knowledge/` follows this shape. It is not a style preference —
each rule exists because retrieval measurably fails without it.

Kept outside `data/knowledge/` on purpose: anything with a `.md` or `.txt`
extension inside that folder gets ingested as knowledge, and this file is not.

---

## Naming

One topic per file, lowercase with hyphens: `acidity.md`, `hair-fall.md`,
`period-pain.md`. The filename is what shows up as the source on a cited answer.

## Template

```markdown
---
topic: Acidity & Heartburn
aliases: acidity, heartburn, amlapitta, acid reflux, khatti dakar,
  seene mein jalan, pet mein jalan, khatta pani, jalan
---

# Acidity & Heartburn (Amlapitta)

## What It Is
## Root Cause
## Changes To Make
## Food Chart
## Daily Routine
## Yoga & Breathing
## Home Remedies
## When To See A Doctor
```

## The rules, and why each one exists

**1. Front matter is mandatory.**
`scripts/ingest_knowledge.py` parses it and prepends
`[Topic: … | also called: …]` to *every* chunk of the file.

Notes get split at ~800 characters, so a file becomes four or five chunks and
only the first one contains the title. Without the stamp, the "Yoga & Breathing"
section of `acidity.md` is an anonymous list of asanas that no acidity query can
match. Measured on the old corpus: `acidity gas` scored **−0.018** and missed a
file entirely about acidity.

An unconverted note still ingests — the script warns and moves on — it just
retrieves badly.

**2. `aliases:` is doing more work than the rest of the file.**
Include English, Hinglish, Hindi-in-Latin-letters, and the Sanskrit name.
8–15 entries. Write what a user actually types: `neend nahi aati`, `kabz`,
`sar dard`, `khatti dakar`, `baal jhadna`.

This is also what the topic-match guard in `src/retrieval/knowledge.py` checks a
query against, so a missing alias means both a weaker vector match and a chunk
the guard may drop.

Indented continuation lines are folded into the previous key, so a long alias
list can wrap freely.

**3. Exactly these eight `##` headings, in this order.**
Six of them — Root Cause, Changes To Make, Food Chart, Daily Routine,
Yoga & Breathing, When To See A Doctor — are the same six the consultation
answer is assembled from (`src/consult/sections.py`, `SECTION_LIBRARY`). A
retrieved note therefore maps 1:1 onto the reply, and the model only has to
personalise it instead of inventing structure.

**4. Keep each section under ~700 characters.**
The splitter cuts at 800. Staying under it keeps each section whole inside one
chunk, so a retrieved chunk is a complete thought rather than half a food list.

**5. Bullets, not paragraphs. One idea per line.**
Bullets survive chunking and retrieve better than prose.

**6. Never name a medicine, brand, tablet, syrup, or dosage.**
`SYSTEM_RULES` in `src/prompts.py` forbids the assistant from doing this.
Content that contains it will push the model into breaking its own rules.

**7. `When To See A Doctor` is never optional.**
`ALWAYS_INCLUDED` in `sections.py` forces it into every answer, so it must be
specific and genuinely useful — real red flags, not a generic disclaimer.

**8. For conditions with real medical treatment** (diabetes, thyroid, BP,
cholesterol, PCOS), say plainly in `What It Is` that the page is lifestyle
support and does not replace the doctor's treatment, and that prescribed
medicine must never be stopped on its own.

**9. Where Ayurvedic evidence is thin, say so** rather than filling the gap.
An honest "this needs a doctor's diagnosis" is worth more than an invented remedy.

---

## After adding or editing a file

```powershell
cd backend-python
.\.venv\Scripts\python.exe scripts\ingest_knowledge.py
```

Ingestion is idempotent — chunk ids are content hashes, so re-running overwrites
in place and deletes chunks removed from a note. Editing the front matter changes
every chunk's id, which is intended: the old ones are cleaned up as stale.

Then check retrieval actually improved:

```powershell
.\.venv\Scripts\python.exe -c "from src import knowledge; print(max([s for _,s in knowledge.search_knowledge_scored('your query here', 4)]))"
```

A topic that has a file should score clearly above `MIN_RELEVANCE`
(`src/retrieval/knowledge.py`); a topic that has none should score below it, so
the assistant answers from general knowledge instead of from the wrong note.
