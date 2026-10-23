"""What the assistant is for a given turn: prompt, retrieval options and model.

THE extension seam for future assistants (for example a tutor with its own
instructions and retrieval filters). Retrieval options are chosen here, server-side; a
client can never supply them.

The system prompt is the frozen SYSTEM_PROMPT, followed by what the student's own settings add
(app/learning/tutor.py) when they add anything. A student who has set nothing gets exactly
SYSTEM_PROMPT (tests/test_legacy_tutor.py). The teaching defaults (app/chat/teaching.py, only when
TUTOR_TEACHING_POLICY is on) go just before the student's settings, which come first. What the latest
message asks for, when the intent router applies an intent (INTENT_ROUTER, app/intents), comes after
the settings: one guidance line; with no intent the prompt is as it was. While STUDY_SCOPE is on, the
study scope's policy (app/intents/scope.py) comes right after the frozen prompt, on every turn.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.chat.teaching import TEACHING_POLICY
from app.db.models import Conversation, User
from app.intents.scope import prompt_block
from app.intents.taxonomy import INTENTS
from app.learning.context import StudentContext
from app.learning.tutor import build_tutor_instructions
from app.rag.graph import RetrievalOptions

SYSTEM_PROMPT = r"""You are a helpful, knowledgeable general-purpose AI assistant.
- Answer the user's question directly and clearly; explain concepts step by step when that helps.
- Follow the user's instructions about format, length, tone and language.
- If you are not sure about something, say so. Never invent facts, sources, quotes or numbers.
- Name a textbook page, chapter or exercise number only when the reference material shows it.
- Ask a short clarifying question only when the request is genuinely ambiguous.
- Use Markdown when it improves readability: headings, lists, tables, fenced code blocks with a
  language tag, and LaTeX math ($...$ inline, $$...$$ for blocks).

Study formatting, only where it genuinely helps (never wrap a whole answer in cards):
- Study card: a line `:::type` or `:::type[Title]`, the content, then a line `:::`. Types: note,
  important, warning, definition, example, steps (a worked solution as a numbered list), answer
  (the final result), takeaway, formula. Never put a card inside another card.
- Chemistry and units go in maths: $\ce{2H2 + O2 -> 2H2O}$, $\pu{9.8 m s^-2}$. Subscripts and
  superscripts only in maths: $H_2O$, $x^2$, $6.02 \times 10^{23}$.
- Diagrams and flowcharts: a ```mermaid block.
- Charts: a ```chart block of JSON: {"type": "bar", "title": "...", "labels": [...], "datasets":
  [{"label": "...", "data": [numbers]}]}; type is bar, line, pie, doughnut, scatter or radar.
- Program output: a ```output block.
- Cite sources inline only, like [1] or [F1]; never write your own list of sources."""

# Interactive practice blocks. The web app renders them whenever a reply contains them; the model
# is taught them only when TUTOR_INTERACTIVE_BLOCKS is on (an owner decision, docs/deployment.md).
INTERACTIVE_BLOCKS = r"""Interactive practice, only when the student asks to practise, revise or be tested.
Write a fenced code block whose language is the type and whose body is one JSON object:
- mcq: {"question": "...", "options": ["...", "..."], "answer": "B", "explanation": "..."}
- quiz: {"title": "...", "questions": [mcq objects]}
- flashcards: {"title": "...", "cards": [{"front": "...", "back": "..."}]}
- fill-blank: {"text": "Water boils at [[100]] °C at sea level.", "explanation": "..."}
- graph: {"functions": [{"expr": "x^2 - 2*x", "label": "f(x)"}], "x": [-5, 5]}
- diagram: {"nodes": [{"id": "a", "label": "...", "detail": "..."}], "edges": [{"from": "a", "to": "b"}]}
A test of several questions, even one asked for "one by one", is ONE quiz block with every question
asked for (at most 30): the app shows them one at a time and records the answers. An exercise of
several sentences is ONE fill-blank block (at most 20 blanks). At most one practice block (mcq, quiz
or fill-blank) per reply; never spread one over several replies. The app records the answers to
tests and fill-blank exercises and tells you the results; flashcards, graphs and diagrams are not
recorded, so if asked how they did with those, say so.
Show an attached file on its own line with ::file{ref=F1}, or one page of an attached PDF with
::pdf{ref=F1 page=3}. For a file the student can download, put its name after the language:
```csv filename="marks.csv"."""

# The same blocks when tests come from the question bank (QUESTION_BANK_TESTS, app/qbank/chat_tests.py):
# the model never writes a test's questions; it names a chapter and the app sets the test.
BANK_BLOCKS = r"""Interactive blocks, only where they genuinely help. Write a fenced code block (three backticks,
never a ::: card) whose language is the type and whose body is one JSON object:
- flashcards: {"title": "...", "cards": [{"front": "...", "back": "..."}]}
- fill-blank: {"text": "Water boils at [[100]] °C at sea level.", "explanation": "..."}
- graph: {"functions": [{"expr": "x^2 - 2*x", "label": "f(x)"}], "x": [-5, 5]}
- diagram: {"nodes": [{"id": "a", "label": "...", "detail": "..."}], "edges": [{"from": "a", "to": "b"}]}
An exercise of several sentences is ONE fill-blank block (at most 20 blanks). At most one practice block
per reply; tests come only from the bank, exercises may be written by you. The app records the answers to
fill-blank exercises and tells you the results; flashcards, graphs and diagrams are not recorded, so if
asked how they did with those, say so.
Tests, quizzes, MCQs and practice questions come only from the app's question bank of stored
questions: never write test questions, options or answers yourself, in any form. When the student
asks to be tested or to practise, set the test at once, without asking anything first: one short line,
then this fenced block on its own lines, exactly in this form (the language is question-bank):
```question-bank
{"chapter": "LEPH1-CH01", "count": 6, "difficulty": "hard"}
```
"chapter" is a chapter id from the question bank list below, copied exactly (never invent one).
"topics" (optional) are particular topics of that chapter, each in a few words or its number. Add them
only when the student or this chat named particular topics: a request for a chapter ("6 hard MCQs
from chapter 1") has no "topics", and its test covers the whole chapter. When the student says "test
me on this" or names no chapter, set the test on what this chat has been about: its chapter and the
topics it covered, e.g. after a chat about the pH scale:
{"chapter": "JESC1-CH02", "topics": ["pH scale"], "count": 5, "difficulty": "mixed"}. "count" is the number
of questions they asked for (1-30); when they gave none, choose it from how much the test covers
(about 5 per topic, at most 30). "difficulty" is what they asked for (easy, medium or hard), else mixed.
A mock test over several chapters of one subject names them all instead: {"chapters": ["JESC1-CH01",
"JESC1-CH02"], "count": 25} (at most 3 chapters, no "topics").
The app replaces the block with the test, shows the questions one at a time, checks the answers and
tells you the results. Only if no list is given, or the chapter is not in it, or it is unclear which
chapter they mean, ask which chapter.
Show an attached file on its own line with ::file{ref=F1}, or one page of an attached PDF with
::pdf{ref=F1 page=3}. For a file the student can download, put its name after the language:
```csv filename="marks.csv"."""


# An intent the router applied (app/intents/taxonomy.py): its guidance, after the student's settings.
INTENT_HEADING = "## What the latest message asks for"
INTENT_NOTE = "This is the app's reading of the message. The student's own words come first, then their settings above."


def intent_block(intent: str | None) -> str:
    """What the tutor is told about an applied intent; "" for none, or for one whose default way is right."""
    guidance = INTENTS[intent].guidance if intent in INTENTS else ""
    return f"{INTENT_HEADING}\n{guidance}\n{INTENT_NOTE}" if guidance else ""


@dataclass(frozen=True)
class AssistantConfig:
    system_prompt: str
    # None = no retrieval for this assistant. Defaults search every source the user may see.
    retrieval: RetrievalOptions | None = field(default_factory=RetrievalOptions)
    model: str | None = None  # None = the provider's configured default
    temperature: float | None = None  # None = settings.llm_temperature


# Voice mode (app/voice): the reply is read aloud by an English voice, sentence by sentence, as it is written.
VOICE_TURN = (
    "This message was spoken in voice mode: your reply will be read aloud by an English voice as you write it, "
    "and it also stays in the chat. Reply in English, in short, natural spoken sentences, most important first; "
    "keep it brief unless the student asks for more. Do not use tables, code blocks, diagrams or headings. Say "
    'formulas, symbols and units in words (for example, "x squared plus 2x" or "9.8 metres per second '
    'squared"), keeping every number exact.'
)


def system_prompt_for(
    student: StudentContext | None,
    interactive: bool = False,
    tests: str = "",
    *,
    teaching: bool = False,
    bank: str | None = None,
    intent: str | None = None,
    scoped: bool = False,
    scope: str | None = None,
    voice: bool = False,
) -> str:
    """The frozen prompt, then the teaching defaults, then what the student's settings add, then what
    the latest message asks for (`intent`, applied by the intent router), then the question bank's
    chapters (on a turn that asks for a test), then the chat's practice tests as the app recorded them
    (app/assessments/state.py). Each part only when it says something. `bank` None: the model writes
    tests itself (QUESTION_BANK_TESTS off). `scoped` (STUDY_SCOPE on): the study scope's policy right after
    the frozen prompt, with the line for this turn's `scope` decision, if it has one."""
    blocks = INTERACTIVE_BLOCKS if bank is None else BANK_BLOCKS
    prompt = f"{SYSTEM_PROMPT}\n\n{blocks}" if interactive else SYSTEM_PROMPT
    keep = prompt_block(scope) if scoped else ""
    policy = TEACHING_POLICY if teaching else ""
    instructions = build_tutor_instructions(student)
    spoken = VOICE_TURN if voice else ""
    asks = intent_block(intent)
    chapters = bank if interactive and bank else ""
    return "\n\n".join(part for part in (prompt, keep, policy, instructions, spoken, asks, chapters, tests) if part)


def retrieval_for(student: StudentContext | None) -> RetrievalOptions:
    """The student's curriculum from their settings (their class, their subjects): the NCERT source
    ranks those books first (app/rag/ncert.py). Nothing set: no preference."""
    if student is None:
        return RetrievalOptions()
    grade = re.fullmatch(r"Class (\d{1,2})", student.grade or "")
    return RetrievalOptions(
        classes=(int(grade.group(1)),) if grade else (),
        subjects=tuple(subject.name for subject in student.subjects),
    )


def resolve_assistant_config(
    user: User | None,
    conversation: Conversation | None,
    student: StudentContext | None = None,
    *,
    interactive: bool = False,
    tests: str = "",
    teaching: bool = False,
    bank: str | None = None,
    intent: str | None = None,
    search: bool = True,
    scoped: bool = False,
    scope: str | None = None,
    voice: bool = False,
) -> AssistantConfig:
    """`intent`: what the intent router read in the latest message (app/intents/taxonomy.py); an intent
    answered from the app's own records searches no knowledge. `search` False: no knowledge search on
    this turn (small talk that opens a chat). Attached files are read either way (app/rag/graph.py)."""
    wanted = INTENTS.get(intent)
    search = search and (wanted is None or wanted.retrieval)
    return AssistantConfig(
        system_prompt=system_prompt_for(
            student,
            interactive,
            tests,
            teaching=teaching,
            bank=bank,
            intent=intent,
            scoped=scoped,
            scope=scope,
            voice=voice,
        ),
        retrieval=retrieval_for(student) if search else None,
    )
