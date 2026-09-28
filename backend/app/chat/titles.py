"""Chat titles, ChatGPT-style: a few words naming the topic, set once from the first answered question.

Deterministic and model-free (no second LLM call per conversation). Sources, in order:

1. the question, when it has a common request shape: "explain X", "what is X", "how do X",
   "difference between X and Y", "solve X", "X kya hai" (Hinglish), "X क्या है";
2. the reply's first real heading (not "Introduction", "Answer", "Step 1", ...);
3. the question's own first words, minus greetings and filler.

Every candidate passes one gate (1-6 words, real letters, not only generic words); one that fails falls
through to the next source, and when none passes the conversation keeps "New chat". Titles are plain
text: markup, links, code, maths and emoji never survive `_strip` and `_words`.
"""

from __future__ import annotations

import re
import unicodedata

from app.progress.learning import SMALL_TALK

MAX_WORDS = 6
MAX_CHARS = 48
_MAX_WORD = 30  # longer "words" are hashes, URLs remains or keyboard mashing
_QUESTION_CHARS = 2000  # only the start of a message or reply is read, so size never costs more
_REPLY_LINES = 60

SMALL = frozenset("a an the and or of in on at to for with by from as vs via into per ka ki ke".split())
STOPWORDS = SMALL | frozenset(
    "is are was were be been am do does did it this that these those my your our their its his her me i "
    "you we they he she what which how why when where who whom can could would should will shall may might "
    "must not no yes so if then than there here".split()
)
GENERIC = frozenset(
    "introduction intro overview summary conclusion answer answers explanation explanations solution "
    "solutions step steps example examples note notes key point points definition definitions result "
    "results final question questions doubt doubts help query queries topic topics detail details source "
    "sources reference references explained explain thing things something anything everything problem "
    "problems equation equations sum sums numerical numericals chat new sure okay ok great here here's "
    "heres let's lets hint hints tip tips".split()
)
# "Tell me something interesting" has no topic to name.
_VAGUE = frozenset("something anything everything someone somebody anyone".split())
# Words that carry no topic, dropped anywhere in a candidate.
_DROP = frozenset("their own my our your its his her exactly actually basically really very just simply".split())

# Greetings, politeness and "I have a doubt" framing at the start of a question (lowercase).
_FILLER = re.compile(
    r"^(?:hi+|hello+|hey+|hlo|namaste|namaskar|good (?:morning|afternoon|evening)|ok(?:ay)?|so|sir|"
    r"ma'?am|mam|madam|bhai|yaar|dear|please|pls|plz|kindly|quick question|"
    r"(?:can|could|would|will) (?:you|u)(?: please| pls| plz)?|kya (?:aap|ap|tum)|mujhe|muje|mujhko|"
    r"i(?:'m| am) (?:confused|stuck)(?: (?:about|with|by|on|in))?|"
    r"i (?:don'?t|do not|didn'?t|did not|can'?t|cannot) (?:understand|get)|"
    r"i (?:want|wanna|need|would like|'d like) to (?:know|learn|understand|ask)(?: about)?|"
    r"i (?:want|need)(?: some)?(?: help)?(?: (?:with|in|on))?|help me(?: (?:with|in|on))?|"
    r"i (?:have|had|got) (?:a |an |one )?(?:doubt|question|query)(?: (?:in|on|about|regarding|related to))?|"
    r"(?:mera|meri|my) (?:doubt|question|query|sawal)(?: (?:is|hai))?(?: that)?|"
    r"(?:ek|one) (?:doubt|question|sawal)(?: hai)?|(?:doubt|question|query)(?: (?:in|on|about|regarding))?|"
    r"to)(?:\s+|$)"
)
# Where a topic ends: "... in detail", "... with examples", "... and why ...".
_CUT = re.compile(
    r"\s(?:in (?:detail|details|short|brief|simple|easy|hindi|english|hinglish|points)|step by step|"
    r"with (?:an |a |some )?(?:examples?|diagrams?|figures?|explanation)|for (?:class|grade|std|standard) \w+|"
    r"for (?:a |an )?(?:beginners?|kids?|children|students?)|"
    r"please|pls|plz|kindly|briefly|simply|shortly|properly|clearly|"
    r"and (?:also|why|how|what|when|where|which|who|give|explain|tell|its|their|it's)|also|so that|because|"
    r"since|if (?:possible|you can)|using|by using|i (?:don'?t|do not|didn'?t|did not|can'?t|cannot)|"
    r"samjhao|samjha(?:o|iye|do|dijiye| do| dijiye| sakte| sakti)?|batao|bataiye|bata do|explain)(?=\s|$)"
)
# When a topic is still too long, it may end before its first prepositional phrase.
_PREP = re.compile(
    r"\s(?:in|at|on|during|for|with|without|from|into|through|under|over|after|before|using|by|when|while|where)\s"
)

_ART = r"(?:(?:the|a|an)\s+)?"
_QUESTION_WORD = re.compile(r"^(?P<q>how|why|who|whom|when|where|which)\s+(?P<rest>.+)$")
_OF = r"(?:(?:concept|idea|process|meaning|topic|chapter)\s+(?:of\s+)?)?"
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern), kind)
    for pattern, kind in (
        (
            r"^(?:(?:what|whats|what's)\s+(?:(?:is|are)\s+)?)?(?:the\s+)?(?:differences?|distinguish|compare|comparison|"
            r"contrast)\s+(?:between\s+|of\s+)?(?P<a>.+?)\s+(?:and|vs|versus|with|&)\s+(?P<b>.+)$",
            "versus",
        ),
        (r"^(?P<a>.+?)\s+(?:vs|versus)\s+(?P<b>.+)$", "versus"),
        (
            rf"^(?:define|definition of|meaning of|(?:what|whats|what's)\s+(?:is\s+)?the\s+(?:meaning|definition)"
            rf"\s+of)\s+{_ART}(?P<topic>.+)$",
            "definition",
        ),
        (r"^what\s+(?:does|do)\s+(?P<topic>.+?)\s+(?:mean|stand for)$", "meaning"),
        (
            rf"^(?:(?:what|wat)\s+(?:is|are|was|were|r)|whats|what's)\s+(?:meant by\s+)?{_ART}{_OF}{_ART}"
            r"(?P<topic>.+)$",
            "explained",
        ),
        (
            r"^(?:explain|describe|elaborate(?:\s+on)?|teach(?:\s+me)?|tell\s+me(?:\s+something)?\s+about|tell\s+me|"
            r"tell\s+about|understand|clarify|discuss|summari[sz]e|give\s+(?:me\s+)?(?:an?\s+)?(?:explanation|"
            r"overview|summary|introduction|notes?)\s+(?:of|on|about|for)|(?:short\s+|brief\s+)?notes?\s+on|"
            rf"what\s+do\s+you\s+(?:mean|know)\s+(?:by|about))\s+(?:me\s+)?(?:about\s+)?{_ART}{_OF}{_ART}"
            r"(?P<topic>.+)$",
            "explained",
        ),
        (
            r"^(?P<verb>solve|calculate|compute|find|evaluate|simplify|integrate|differentiate|derive|prove|"
            r"factori[sz]e|factor)\s+(?:(?:the|a|an|this|these|that|following|given)\s+)*(?P<topic>.+)$",
            "solving",
        ),
        (_QUESTION_WORD.pattern, "question"),
        (
            r"^(?P<topic>.+?)\s+(?:ka|ki|ke|का|की|के)\s+(?:matlab|meaning|arth|definition|मतलब|अर्थ)(?:\s.*)?$",
            "meaning",
        ),
        (
            r"^(?P<topic>.+?)\s+(?:kya|kyaa|kyu|kyon|kaise|kese|samjhao|samjha(?:o|iye|do|dijiye)?|batao|bataiye|"
            r"bata|explain|क्या|कैसे|क्यों|समझाओ|समझाइए|बताओ|बताइए)(?:\s.*)?$",
            "explained",
        ),
    )
)
_GERUND = {
    "solve": "solving",
    "calculate": "calculating",
    "compute": "computing",
    "find": "finding",
    "evaluate": "evaluating",
    "simplify": "simplifying",
    "integrate": "integrating",
    "differentiate": "differentiating",
    "derive": "deriving",
    "prove": "proving",
    "factorise": "factorising",
    "factorize": "factorizing",
    "factor": "factoring",
}
_SUFFIX = {"explained": "explained", "definition": "definition", "meaning": "meaning"}

_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*$|^(?:\*\*|__)([^*_].*?)(?:\*\*|__):?$")
_NUMBERING = re.compile(r"(?i)^(?:\d+[.)]|step\s+\d+\s*[:.)-]?|part\s+[a-z0-9]+\s*[:.)-]?|[ivx]+[.)])\s*")
_CHATTY_HEADING = re.compile(
    r"^(?:let'?s|here'?s|here is|sure|okay|great|so|now|first|next|finally|in summary|to summari[sz]e|"
    r"quick answer|short answer|the answer|your answer)\b"
)
_CLAUSE = re.compile(r"[\n?!;]+|[.:](?=\s|$)|,\s+|\s[-–—]\s")
_SYMBOL = re.compile(r"[=+*/^<>±×÷√∫∑∞≤≥≠]|\w\(\w{0,3}\)|^\(\w{0,3}\)$")  # f(x), sin(x), (1)
_DASH_NUMBER = re.compile(r"^[-−–]$|\d[-−]|[-−]\d")
_TWO_LETTERS = re.compile(r"[^\W\d_]{2,}")
_WORD_SLASH = re.compile(r"(?<=[^\W\d_][^\W\d_])/(?=[^\W\d_]{2})")


def _strip(text: str) -> str:
    """Remove everything that is not prose: HTML, code, maths, images, links' targets, URLs."""
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"(?is)<(script|style)\b.*?</\1\s*>", " ", text)
    text = re.sub(r"<[^>]{0,200}>", " ", text)
    text = re.sub(r"(?s)```.*?(?:```|$)", " ", text)
    text = re.sub(r"`[^`\n]*`", " ", text)
    text = re.sub(r"(?s)\$\$.*?(?:\$\$|$)", " ", text)
    text = re.sub(r"\$[^$\n]*\$", " ", text)
    text = re.sub(r"(?s)\\\(.*?\\\)|\\\[.*?\\\]", " ", text)
    text = re.sub(r"!\[[^\]\n]*\]\([^)\n]*\)", " ", text)
    text = re.sub(r"\[([^\]\n]*)\]\([^)\n]*\)", r"\1", text)
    return re.sub(r"(?i)\b(?:https?://|www\.)\S+|\S+@\S+\.\w+|javascript:\S*", " ", text)


def _without_math(text: str) -> str:
    """Drop runs of maths tokens ("2x + 3 = 7", "F=ma"); a run counts only if it has an operator."""
    tokens, kept, run, has_operator = _WORD_SLASH.sub(" ", text).split(), [], [], False
    for token in [*tokens, ""]:
        # "x^2", "5x-3" and a lone "-" are maths; "COVID-19" is a word.
        operator = bool(_SYMBOL.search(token)) or (bool(_DASH_NUMBER.search(token)) and not _TWO_LETTERS.search(token))
        if token and (operator or not _TWO_LETTERS.search(token)):
            run.append(token)
            has_operator = has_operator or operator
            continue
        if not has_operator:
            kept.extend(run)
        run, has_operator = [], False
        if token:
            kept.append(token)
    return " ".join(kept)


def _words(text: str) -> list[str]:
    """Plain words: letters (any script, with their combining marks), digits, ' - &; nothing else."""
    chars: list[str] = []
    for ch in text.replace("’", "'").replace("‘", "'"):
        category = unicodedata.category(ch)
        if category == "Cf" or 0xFE00 <= ord(ch) <= 0xFE0F:
            continue  # zero-width joiners inside a word; emoji variation selectors
        if category[0] in "LN" or ch in "'-&" or (category[0] == "M" and chars and chars[-1] != " "):
            chars.append(ch)
        else:
            chars.append(" ")
    words = []
    for piece in "".join(chars).split():
        word = "and" if piece == "&" else piece.strip("'-")
        if any(unicodedata.category(ch)[0] in "LN" for ch in word):
            words.append(word)
    return words


def _letters(word: str) -> int:
    return sum(ch.isalpha() for ch in word)


def _passes(words: list[str], limit: int = MAX_WORDS) -> bool:
    """The gate every candidate passes: short, made of real words, and not only filler."""
    if not 1 <= len(words) <= limit or len(" ".join(words)) > MAX_CHARS:
        return False
    if any(len(word) > _MAX_WORD for word in words):
        return False
    if sum(_letters(word) for word in words) < 3 or not any(_letters(word) >= 3 for word in words):
        return False
    return not all(word in GENERIC or word in STOPWORDS or word in SMALL_TALK or word.isdigit() for word in words)


def _trim(words: list[str], *, lead: bool = True) -> list[str]:
    while lead and words and words[0] in SMALL:
        words = words[1:]
    while words and words[-1] in STOPWORDS:
        words = words[:-1]
    return words


def _reduce(text: str, limit: int, *, lead: bool = True) -> list[str]:
    """A topic without its trailing clauses and filler; shortened at a preposition if still too long."""
    cut = _CUT.search(text)
    if cut:
        text = text[: cut.start()]
    words = _trim([word for word in text.split() if word not in _DROP], lead=lead)
    if len(words) > limit:
        joined = " ".join(words)
        prefixes = (_trim(joined[: match.start()].split(), lead=lead) for match in _PREP.finditer(joined))
        return max((p for p in prefixes if 2 <= len(p) <= limit), key=len, default=words)
    return words


def _is_latin(words: list[str]) -> bool:
    return all("LATIN" in unicodedata.name(ch, "") for word in words for ch in word if ch.isalpha())


def _from_pattern(kind: str, match: re.Match[str]) -> list[str] | None:
    if kind == "versus":
        a, b = _reduce(match["a"], 3), _reduce(match["b"], 3)
        if not (_passes(a, 3) and _passes(b, 3)):
            return None
        return [*a, "vs", *b]
    if kind == "question":
        rest = _reduce(match["rest"], MAX_WORDS - 1, lead=False)
        return [match["q"], *rest] if _passes(rest, MAX_WORDS - 1) else None
    if kind == "explained" and (question := _QUESTION_WORD.match(match["topic"])):
        return _from_pattern("question", question)  # "explain how X" -> "How X"
    topic = _reduce(match["topic"], MAX_WORDS - 1)
    if not _passes(topic, MAX_WORDS - 1) or topic[0] in _VAGUE:
        return None
    if not _is_latin(topic):
        return topic  # "प्रकाश संश्लेषण", not "प्रकाश संश्लेषण Explained"
    if kind == "solving":
        return [_GERUND.get(match["verb"], "solving"), *topic]
    return [*topic, _SUFFIX[kind]]


def _title_case(words: list[str], keep: dict[str, str]) -> str:
    out = []
    for index, word in enumerate(words):
        if word in keep:
            out.append(keep[word])
        elif index and word in SMALL:
            out.append(word)
        else:
            out.append(word[:1].upper() + word[1:])
    return " ".join(out)


def _keep_case(words: list[str]) -> dict[str, str]:
    """Acronyms and mixed case as the student wrote them (DNA, pH, mRNA), unless they wrote in capitals."""
    letters = [ch for word in words for ch in word if ch.isalpha() and ch.isascii()]
    if len(letters) >= 4 and all(ch.isupper() for ch in letters):
        return {}
    return {
        word.lower(): word
        for word in words
        if len(word) > 1 and (word.isupper() or any(ch.isupper() for ch in word[1:]))
    }


def _without_filler(text: str) -> str:
    for _ in range(12):
        match = _FILLER.match(text)
        if not match or not match.end():
            break
        text = text[match.end() :]
    return text.strip()


def _clauses(question: str) -> list[tuple[str, list[str]]]:
    """The question's clauses as (lowercase text without filler, original-case words), non-empty only."""
    out = []
    head = question[:_QUESTION_CHARS]
    if len(question) > _QUESTION_CHARS and " " in head:
        head = head[: head.rindex(" ")]  # never a half word
    for part in _CLAUSE.split(_strip(head)):
        words = _words(_without_math(part))
        text = _without_filler(" ".join(word.lower() for word in words))
        if text:
            out.append((text, words))
    return out


def _heading(reply: str) -> tuple[list[str], dict[str, str]] | None:
    """The reply's first heading that names something (and its casing), outside code and display maths."""
    fence = math = False
    for raw in reply[: _QUESTION_CHARS * 4].splitlines()[:_REPLY_LINES]:
        line = raw.strip()[:300]
        if line.startswith(("```", "~~~")):
            fence = not fence
            continue
        if line.startswith("$$"):
            if not (len(line) >= 4 and line.endswith("$$")):
                math = not math
            continue
        if fence or math:
            continue
        match = _HEADING.match(line)
        if not match:
            continue
        text = _NUMBERING.sub("", _strip(match.group(1) or match.group(2) or ""))
        words = _words(_without_math(text))
        lowered = [word.lower() for word in words]
        if _CHATTY_HEADING.match(" ".join(lowered)):
            continue
        lowered = _trim([word for word in lowered if word not in _DROP])
        if _passes(lowered):
            return lowered, _keep_case(words)
    return None


def topic_title(question: str, reply: str) -> tuple[str, str] | None:
    """(title, source) for a conversation's first answered question, or None to keep "New chat".

    Deterministic: the same question and reply always give the same title. Never raises on any text.
    """
    clauses = _clauses(question)
    keep = _keep_case([word for _, words in clauses for word in words])
    for text, _ in clauses[:3]:
        for pattern, kind in _PATTERNS:
            match = pattern.match(text)
            if match:
                words = _from_pattern(kind, match)
                if words and len(words) <= MAX_WORDS and len(" ".join(words)) <= MAX_CHARS:
                    return _title_case(words, keep), "question"
                break  # a clause gets one reading; a failed one falls through to the next source
    heading = _heading(reply)
    if heading:
        return _title_case(*heading), "heading"
    for text, _ in clauses[:3]:
        text = re.sub(r"^(?:i'm|im|i am|we're|we are|i|we)\s+", "", text)
        words = _reduce(text, MAX_WORDS, lead=False)
        words = [word for i, word in enumerate(words) if len(word) <= _MAX_WORD and (not i or word != words[i - 1])]
        words = _trim(words[:MAX_WORDS], lead=False)
        if _passes(words):
            return _title_case(words, keep), "fallback"
    return None
