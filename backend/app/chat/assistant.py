"""What the assistant is for a given turn: prompt, retrieval options and model.

THE extension seam for future assistants (for example a tutor with its own
instructions and retrieval filters). Retrieval options are chosen here, server-side; a
client can never supply them.

The system prompt is the frozen SYSTEM_PROMPT, followed by what the student's own settings add
(app/learning/tutor.py) when they add anything. A student who has set nothing gets exactly
SYSTEM_PROMPT (tests/test_legacy_tutor.py). The teaching defaults (app/chat/teaching.py, only when
TUTOR_TEACHING_POLICY is on) go just before the student's settings, which come first.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.chat.teaching import TEACHING_POLICY
from app.db.models import Conversation, User
from app.learning.context import StudentContext
from app.learning.tutor import build_tutor_instructions
from app.rag.graph import RetrievalOptions

SYSTEM_PROMPT = r"""You are a helpful, knowledgeable general-purpose AI assistant.
- Answer the user's question directly and clearly; explain concepts step by step when that helps.
- Follow the user's instructions about format, length, tone and language.
- If you are not sure about something, say so. Never invent facts, sources, quotes or numbers.
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


@dataclass(frozen=True)
class AssistantConfig:
    system_prompt: str
    # None = no retrieval for this assistant. Defaults search every source the user may see.
    retrieval: RetrievalOptions | None = field(default_factory=RetrievalOptions)
    model: str | None = None  # None = the provider's configured default
    temperature: float | None = None  # None = settings.llm_temperature


def system_prompt_for(
    student: StudentContext | None, interactive: bool = False, tests: str = "", *, teaching: bool = False
) -> str:
    """The frozen prompt, then the teaching defaults, then what the student's settings add, then the
    chat's practice tests as the app recorded them (app/assessments/state.py). Each part only when
    it says something."""
    prompt = f"{SYSTEM_PROMPT}\n\n{INTERACTIVE_BLOCKS}" if interactive else SYSTEM_PROMPT
    policy = TEACHING_POLICY if teaching else ""
    instructions = build_tutor_instructions(student)
    return "\n\n".join(part for part in (prompt, policy, instructions, tests) if part)


def resolve_assistant_config(
    user: User | None,
    conversation: Conversation | None,
    student: StudentContext | None = None,
    *,
    interactive: bool = False,
    tests: str = "",
    teaching: bool = False,
) -> AssistantConfig:
    return AssistantConfig(system_prompt=system_prompt_for(student, interactive, tests, teaching=teaching))
