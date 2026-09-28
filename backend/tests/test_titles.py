"""Chat titles (app/chat/titles.py): short, meaningful, plain text, deterministic, never a crash."""

import random
import time
import unicodedata

import pytest

from app.chat.titles import GENERIC, MAX_CHARS, MAX_WORDS, STOPWORDS, topic_title
from app.progress.learning import SMALL_TALK

Q, H, F = "question", "heading", "fallback"
PLAIN = "I have been reading a lot lately"  # matches no request shape, so a reply heading can win

CASES = [
    # Request shapes, English and Hinglish.
    ("Explain photosynthesis", "", ("Photosynthesis Explained", Q)),
    ("Hi, can you please explain photosynthesis?", "", ("Photosynthesis Explained", Q)),
    ("What is the difference between mitosis and meiosis?", "", ("Mitosis vs Meiosis", Q)),
    ("What's the difference between speed and velocity?", "", ("Speed vs Velocity", Q)),
    ("difference between plant cell and animal cell", "", ("Plant Cell vs Animal Cell", Q)),
    ("mitosis vs meiosis", "", ("Mitosis vs Meiosis", Q)),
    ("how do plants make their own food in the dark", "", ("How Do Plants Make Food", Q)),
    ("How to prepare for board exams in 30 days", "", ("How to Prepare for Board Exams", Q)),
    ("why is the sky blue", "", ("Why Is the Sky Blue", Q)),
    ("Who discovered penicillin and when?", "", ("Who Discovered Penicillin", Q)),
    ("Explain Newton's laws of motion with examples", "", ("Newton's Laws of Motion Explained", Q)),
    (
        "Explain how photosynthesis works in plants and why it matters for life",
        "",
        ("How Photosynthesis Works in Plants", Q),
    ),
    (
        "Please explain the concept of the photoelectric effect in simple words",
        "",
        ("Photoelectric Effect Explained", Q),
    ),
    (
        "Explain the causes of World War 1 in detail with examples for class 10",
        "",
        ("Causes of World War 1 Explained", Q),
    ),
    ("Explain photosynthesis and respiration", "", ("Photosynthesis and Respiration Explained", Q)),
    ("Explain photosynthesis, respiration and transpiration", "", ("Photosynthesis Explained", Q)),
    ("What are the laws of motion?", "", ("Laws of Motion Explained", Q)),
    ("whats photosynthesis", "", ("Photosynthesis Explained", Q)),
    ("tell me about the French Revolution", "", ("French Revolution Explained", Q)),
    ("tell me the formula of kinetic energy", "", ("Formula of Kinetic Energy Explained", Q)),
    ("Define osmosis", "", ("Osmosis Definition", Q)),
    ("what does DNA stand for", "", ("DNA Meaning", Q)),
    ("What is DNA replication", "", ("DNA Replication Explained", Q)),
    ("what is pH scale", "", ("pH Scale Explained", Q)),
    ("what is COVID-19", "", ("COVID-19 Explained", Q)),
    ("EXPLAIN PHOTOSYNTHESIS", "", ("Photosynthesis Explained", Q)),
    ("Calculate the area of a circle with radius 7 cm", "", ("Calculating Area of a Circle", Q)),
    ("Solve the quadratic equation x^2 - 5x + 6 = 0", "", ("Solving Quadratic Equation", Q)),
    ("Prove that root 2 is irrational", "", ("Proving Root 2 Is Irrational", Q)),
    ("photosynthesis kya hai", "", ("Photosynthesis Explained", Q)),
    ("Newton ka third law samjhao", "", ("Newton ka Third Law Explained", Q)),
    ("mujhe trigonometry samjhao", "", ("Trigonometry Explained", Q)),
    ("kya aap photosynthesis samjha sakte ho", "", ("Photosynthesis Explained", Q)),
    ("namaste, newton ke laws kya hote hain", "", ("Newton ke Laws Explained", Q)),
    ("Schrödinger equation kya hai", "", ("Schrödinger Equation Explained", Q)),
    ("प्रकाश संश्लेषण क्या है", "", ("प्रकाश संश्लेषण", Q)),  # no English suffix on another script
    # Markup, links, emoji, invisible and full-width characters never reach a title.
    ("<script>alert(1)</script> explain photosynthesis", "", ("Photosynthesis Explained", Q)),
    ("Explain [photosynthesis](https://evil.example/x)", "", ("Photosynthesis Explained", Q)),
    ("Explain photosynthesis 🌱🌱 please", "", ("Photosynthesis Explained", Q)),
    ("​​explain​ photosynthesis️", "", ("Photosynthesis Explained", Q)),
    ("Ｅｘｐｌａｉｎ ｐｈｏｔｏｓｙｎｔｈｅｓｉｓ", "", ("Photosynthesis Explained", Q)),
    ("<img src=x onerror=alert(1)> **bold** [x](javascript:alert(1))", "", None),
    ("explain `rm -rf /` and https://example.com/x?y=1", "", None),
    ("https://example.com/very/long/path", "", None),
    ("🌱🌱🌱", "", None),
    ("What is 2+2", "", None),
    ("explain", "## Overview\n## Summary", None),
    ("hi", "", None),
    ("thanks", "", None),
    # The reply's first real heading, when the question has no request shape.
    ("asdf qwerty", "## Introduction\n## Step 1: Light reactions\n# The Calvin Cycle", ("Light Reactions", H)),
    (PLAIN, "Sure!\n\n```\n# not a heading\n```\n\n## Why Leaves Change Colour\n", ("Why Leaves Change Colour", H)),
    (PLAIN, "## Let's break it down\n**Key Points:**\n### 2. Chlorophyll and Light\n", ("Chlorophyll and Light", H)),
    (PLAIN, "```python\nprint(1)\n```\n## Printing in Python", ("Printing in Python", H)),
    (PLAIN, "[1] Source: NCERT\n\n## Photosynthesis", ("Photosynthesis", H)),
    (PLAIN, "## <img src=x onerror=alert(1)>Photosynthesis <b>Basics</b>", ("Photosynthesis Basics", H)),
    (PLAIN, "$$\n# x\n$$\n| a | b |\n## Answer\n", ("Have Been Reading a Lot Lately", F)),
    # The question's own words, cleaned.
    (
        "I'm confused about why leaves change colour in autumn and what chlorophyll does",
        "",
        ("Why Leaves Change Colour in Autumn", Q),
    ),
    ("I am preparing for my board exams and i want tips for physics", "", ("Preparing for Board Exams", F)),
    ("Solve the equation 2x + 3 = 7", "", ("Solve the Equation", F)),
    ("Give me 5 MCQs on photosynthesis", "", ("Give Me 5 MCQs on Photosynthesis", F)),
    ("Write an essay on pollution", "", ("Write an Essay on Pollution", F)),
    ("tell me something interesting", "", ("Tell Me Something Interesting", F)),
    ("What is... photosynthesis???", "", ("Photosynthesis", F)),
    ("photosynthesis " * 2000, "", ("Photosynthesis", F)),
    ("zzz qqq www", "x" * 20000 + "\n## Late Heading", ("Zzz Qqq Www", F)),  # only the reply's start is read
    ("Explain photosynthesis", "word " * 5000, ("Photosynthesis Explained", Q)),
]


@pytest.mark.parametrize(("question", "reply", "expected"), CASES, ids=[c[0][:40] for c in CASES])
def test_titles(question, reply, expected):
    assert topic_title(question, reply) == expected


ALLOWED = " '-&"


def _assert_safe(result):
    if result is None:
        return
    title, source = result
    words = title.split()
    assert source in {"question", "heading", "fallback"}
    assert 1 <= len(words) <= MAX_WORDS and len(title) <= MAX_CHARS, title
    assert title == title.strip() and "  " not in title
    for ch in title:
        assert unicodedata.category(ch)[0] in "LMN" or ch in ALLOWED, (title, ch)
    assert not all(w.lower() in GENERIC | STOPWORDS | SMALL_TALK or w.isdigit() for w in words), title


VOCAB = (
    "explain what is how why the difference between and vs solve find photosynthesis newton's laws of "
    "motion kya hai samjhao 2x + 3 = 7 x^2 $$ $ ** __ ` ``` # ## [link](http://x.y) <b> </b> <script> "
    "&amp; & - — : ; , . ? ! 🌱 👍🏽 ​ ️ प्रकाश संश्लेषण क्या है التمثيل ñ ü 漢字 \n \t hi thanks "
    "sure here's introduction answer step 1 overview in detail with examples please"
).split(" ")


def test_fuzz_titles_are_always_short_safe_and_deterministic():
    rng = random.Random(20260928)
    for _ in range(500):
        question = " ".join(rng.choice(VOCAB) for _ in range(rng.randint(0, 40)))
        noise = "".join(chr(rng.randint(32, 0x2FFF)) for _ in range(rng.randint(0, 30)))
        reply = "\n".join(rng.choice(["## ", "# ", "**", "", "```", "$$"]) + rng.choice(VOCAB) for _ in range(20))
        for q in (question, noise, question + noise):
            first = topic_title(q, reply)
            _assert_safe(first)
            assert topic_title(q, reply) == first  # deterministic


def test_huge_inputs_are_cheap():
    started = time.perf_counter()
    topic_title("explain " + "photosynthesis " * 5000, ("## heading\n" + "a" * 500 + "\n") * 5000)
    topic_title("$" * 20000 + "`" * 20000 + "<" * 20000, "```" * 20000)
    assert time.perf_counter() - started < 1.0
