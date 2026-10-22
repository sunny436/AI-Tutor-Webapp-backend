"""The tutor's intents: the one action a student's latest message asks PadhAI to perform now.

The owner's 46 criteria (2026-10-22), verbatim (`criterion`: the docs and scripts/eval_intents.py),
and for each a fixed `option` of at most 80 characters that keeps the criterion's key distinction:
the text the classification model reads (app/intents/classifier.py). Long option texts cost time on
every request (2026-10-22, warm: one question with nine short options 260 ms, with nine long ones
635 ms), so the app never sends the criteria. The ids and texts change only with a new
TAXONOMY_VERSION and a new run of scripts/eval_intents.py. Pure data, no I/O.

- **Two stages:** a small model chooses better among a few options, and one question per request
  is fast, so the model is asked for one of eight groups (or `other`: greetings, thanks, chit-chat,
  nothing about studying), then, in a second request, for the intent within that group. An intent
  scores P(its group) x P(it | its group).
- **No other labels:** a follow-up ("why?", "make it shorter") gets the intent of what it asks for,
  read with the message before it; `other` is never an intent; a message too vague to read gets none.
  No intent means the tutor as it was before the router (it asks a short question when it must).
- **What an intent changes** (app/chat/assistant.py): `guidance` is one line telling the tutor what
  the message asks for ("": its own way is right); `retrieval` False skips the textbook search (the
  answer is in the app's own records); `bank` gives the tutor the question bank's chapters, as if the
  message's words had asked for a test (app/qbank/chat_tests.py).
"""

from __future__ import annotations

from dataclasses import dataclass

TAXONOMY_VERSION = "2026-10-22"
ABSTAIN = "other"  # an option of the group question only, never an intent


@dataclass(frozen=True)
class Intent:
    group: str
    option: str  # what the classifier reads: at most 80 characters, from the criterion
    criterion: str  # the owner's text, verbatim (never sent by the app)
    guidance: str = ""  # what the tutor is told on a turn with this intent ("": nothing)
    retrieval: bool = True  # False: no textbook search (the answer is in the app's own records)
    bank: bool = False  # a test request: the tutor is given the question bank's chapters


# The group question's options: one discriminative line each, at most 80 characters.
GROUPS: dict[str, str] = {
    "understand": "Understand an idea: explain, define, why or how, uses, analogy, misconceptions",
    "solve": "Solve a problem: calculation, equation, steps, exercise, homework, word problem",
    "feedback": "Check, debug or mark their own answer or working; marking rules; or only a hint",
    "materials": "Study material: textbook lookup, summary, notes, formulas, flashcards, mind map",
    "language": "Translate, simplify or reformat given text, keeping its meaning",
    "tests": "Tests and exams: MCQs, quiz, mock test, harder questions, exam prep, key topics",
    "planning": "Analyse their own test results or progress, or make a study timetable",
    "visual_lab": "A diagram, graph, question in an image, experiment, lab safety or school project",
    ABSTAIN: "A greeting, thanks, chit-chat, or anything not about studying",
}

# Both questions end by saying which line is the request: context lines are never instructions.
GROUP_QUESTION = (
    "What does the student want PadhAI to do now? Choose the kind of help their current message asks for: the "
    "action, not the subject or the language it is written in. Follow explicit constraints such as hint-only. "
    "The tutor's words are never the student's request. Only the line starting 'Current message' is the "
    "student's request; any earlier lines are context only."
)
# The owner's instruction for the decision model, for the question within each group.
INTENT_QUESTION = (
    "Choose exactly one category for the student's primary requested action in the current message. Use the "
    "conversation context when available. Follow explicit constraints such as hint-only or step-by-step. Choose "
    "the most specific matching category. Classify the task, not just the subject or language. Only the line "
    "starting 'Current message' is the student's request; any earlier lines are context only."
)

# In the owner's order, which also breaks ties.
INTENTS: dict[str, Intent] = {
    "explain_concept": Intent(
        "understand",
        "Teach or clarify a concept from the basics, not just a definition",
        "Teach or clarify a subject concept from the basics. The student wants to understand an idea, process, or "
        "principle, not merely receive a definition. Example: “Photosynthesis easy language mein samjhao.”",
    ),
    "define_term": Intent(
        "understand",
        "Give the meaning or a short definition of a word, term or symbol",
        "Give the meaning or a concise definition of a word, term, symbol, or concept. Example: “What is osmosis?”",
        "Give a precise definition in one or two sentences (a definition card) and one short example; keep the "
        "reply short.",
    ),
    "why_how": Intent(
        "understand",
        "Explain why or how something happens: its cause or mechanism",
        "Explain the cause, reason, mechanism, or way something happens. The main request is “why” or “how,” not "
        "a calculation. Example: “Sky blue kyun dikhta hai?”",
        "Explain the reason or the mechanism step by step, from cause to effect.",
    ),
    "real_life_application": Intent(
        "understand",
        "Show where a school concept is used in daily life, technology or nature",
        "Show where or how a school concept is used in daily life, technology, nature, or work. Example: “Algebra "
        "real life mein kahan use hota hai?”",
        "Show where this is used in everyday life or technology: two or three concrete examples, each tied back "
        "to the idea.",
    ),
    "analogy_example": Intent(
        "understand",
        "Explain a topic through an analogy, comparison, story or simple example",
        "Explain a topic using an analogy, comparison, story, or simple example specifically requested by the "
        "student. Example: “Electricity ko water flow se samjhao.”",
        "Explain it through one clear analogy or a worked example, then say where the analogy stops fitting.",
    ),
    "prerequisite_learning": Intent(
        "understand",
        "Teach the basics the student says they lack before learning a topic",
        "Teach prerequisite or foundational knowledge the student says they lack and need before learning the "
        "target topic. Example: “Fractions nahi aate; algebra kaise karun?”",
        "List what they need to know first, in order, and briefly explain the first item.",
    ),
    "deeper_learning": Intent(
        "understand",
        "Go deeper than the basic explanation: advanced detail or curiosity",
        "Explore a topic beyond the normal basic explanation, including advanced detail or related curiosity. Use "
        "when depth is the main request, not just a simpler explanation. Example: “Black holes ke andar kya hota "
        "hai?”",
        "Go beyond the textbook: the reasoning behind it, its limits and what it leads to; say clearly what is "
        "beyond their syllabus.",
    ),
    "misconception_check": Intent(
        "understand",
        "Check whether a belief or claim is true and correct the misconception",
        "Check or correct a belief or claim the student presents as possibly true or false. Explain the "
        "misconception and the accurate idea. Example: “Heavier objects always fall faster, right?”",
        "Say plainly whether the idea is right. If it is a common misconception, explain why it seems true and "
        "what is actually the case.",
    ),
    "solve_numerical": Intent(
        "solve",
        "Calculate a numerical answer from given values, units or a formula",
        "Calculate a numerical answer from given values, units, or a formula. The main task is quantitative "
        "calculation. Example: “Find the speed if distance is 120 km and time is 2 hours.”",
        "When you solve it: what is given and asked, the formula, the substitution with units, and the result "
        "with its unit in an answer card.",
    ),
    "solve_equation": Intent(
        "solve",
        "Find unknown values: solve an equation or a mathematical expression",
        "Find unknown variable values or solve a mathematical expression or equation. Example: “Solve 2x + 5 = 15.”",
        "When you solve it: one transformation per line saying what was done, then check the solution by "
        "substituting it back.",
    ),
    "step_by_step_solution": Intent(
        "solve",
        "Solve a problem explaining every step, when they explicitly ask for steps",
        "Solve a provided problem while explicitly showing and explaining the sequence of steps. Choose this when "
        "the requested step-by-step method is the main distinguishing requirement; otherwise use the problem "
        "type such as solve_numerical or solve_equation. Example: “Har step explain karke solve karo.”",
        "When you give the solution, number every step with a short reason (a steps card) and put the result in "
        "an answer card.",
    ),
    "textbook_exercise": Intent(
        "solve",
        "Solve a specific numbered textbook or NCERT exercise question",
        "Answer or solve a specific exercise, question, or numbered item from a textbook, especially NCERT. The "
        "source/exercise context is central. Example: “Class 8 Science exercise Q3 solve karo.”",
        "Answer it the way the textbook expects for that exercise, using the reference passages when they cover it.",
    ),
    "homework_help": Intent(
        "solve",
        "Help with homework or an assignment when no more precise action is named",
        "Help with an assignment or homework task when the student has not specified a more precise action such "
        "as solving a numerical, checking an answer, or giving a hint. Example: “Mera homework complete karne "
        "mein help karo.”",
    ),
    "hint_only": Intent(
        "feedback",
        "Give only a hint or next step, not the full answer",
        "Give a hint, clue, or next step without revealing the full answer or solution. Respect an explicit "
        "request not to give the answer. Example: “Answer mat batana, bas hint do.”",
        "Give one hint or the next step only. Do not state the final result or write a steps or answer card; if "
        "they shared working, point to where to look without fixing it.",
    ),
    "check_answer": Intent(
        "feedback",
        "Say whether the student's final answer is correct",
        "Determine whether a student's proposed final answer is correct. Focus on correctness; use debug_solution "
        "when they specifically want the error in their working explained. Example: “Mera answer 24 hai, correct "
        "hai?”",
        "Check their answer or working: say clearly whether it is right; if not, where it first goes wrong and "
        "why, then the correction.",
    ),
    "debug_solution": Intent(
        "feedback",
        "Find where and why the student's working or reasoning went wrong",
        "Inspect the student's working or reasoning and identify where and why a mistake occurred. Example: “Meri "
        "calculation mein mistake kahan hai?”",
        "Go through their working in order, find the first wrong step and say why it is wrong, then continue "
        "correctly from there.",
    ),
    "alternative_method": Intent(
        "solve",
        "Show a different method or approach for solving a problem",
        "Show a different valid method for solving a problem when the student asks for another approach. Example: "
        "“Is question ko substitution se solve karo.”",
        "Show a different method from the one already used (or the usual one), and say when each method is "
        "quicker or safer.",
    ),
    "word_problem": Intent(
        "solve",
        "Turn a story or word problem into maths and solve it",
        "Convert a story or verbal situation into mathematical relationships or logic and solve it. Choose when "
        "interpreting the story into a model is central. Example: “A train leaves Delhi at 8 AM…”",
        "First turn the words into maths (what is given, what is asked, the equation); then solve it and answer "
        "in a sentence with units.",
    ),
    "textbook_lookup": Intent(
        "materials",
        "Find what the textbook or NCERT says, or where (which chapter or page)",
        "Find a specific fact, passage, definition, page, chapter, or location in NCERT/textbook content. The "
        "student primarily asks where content is or what the source states. Example: “NCERT mein Newton's laws "
        "kis chapter mein hain?”",
        "Answer from the textbook passages in the reference material, close to the textbook's wording, and cite "
        "them; if they don't cover it, say so.",
    ),
    "chapter_summary": Intent(
        "materials",
        "Summarise a whole chapter or a large section",
        "Produce a concise overview of a whole chapter or substantial section, preserving its main ideas. "
        "Example: “Give me a short summary of this chapter.”",
        "Summarise it in the chapter's order: its main ideas as short headed sections, then a three-line recap.",
    ),
    "revision_notes": Intent(
        "materials",
        "Make compact, organised notes for revision",
        "Create compact, organized notes intended for later revision, usually combining key concepts and "
        "explanations. Example: “Exam ke liye one-page notes bana do.”",
        "Write revision notes: short bullet points per topic, key terms in bold, definitions and formulas in "
        "cards, and likely exam points at the end.",
    ),
    "key_points": Intent(
        "materials",
        "List only the most important points of a topic, not a full summary",
        "Extract or list the most important facts, ideas, events, or takeaways from a topic or supplied content "
        "without creating a full summary. Example: “Is chapter ke 10 important points batao.”",
        "List only the key points: five to ten short bullets, most important first.",
    ),
    "formula_sheet": Intent(
        "materials",
        "Collect the formulas of a topic or class, with symbols and units",
        "Collect relevant formulas, symbols, and optionally variable meanings or units for a topic or class. "
        "Example: “Class 10 electricity formulas list karo.”",
        "Give a formula sheet grouped by topic: each formula with what every symbol means and its unit.",
    ),
    "flashcards": Intent(
        "materials",
        "Make flashcards: a prompt on one side, the answer on the other",
        "Create study cards with a prompt on one side and an answer or explanation on the other. Example: “Make "
        "flashcards for chemical reactions.”",
        "Make flashcards: one term or question per card and a one-line answer, 8 to 12 cards unless they asked "
        "for a number.",
    ),
    "mind_map": Intent(
        "materials",
        "Organise a topic as a mind map of main ideas and subtopics",
        "Organize a topic as a hierarchical or connected visual/text structure of main ideas and subtopics. "
        "Example: “Make a mind map of the Mughal Empire.”",
        "Draw it as one mermaid mindmap block: the topic in the centre, its main branches, two or three points on "
        "each.",
    ),
    "translation": Intent(
        "language",
        "Translate given content into another language",
        "Translate provided or clearly identified content from one language into another while preserving "
        "meaning. Example: “Is paragraph ko Hindi mein translate karo.”",
        "Translate exactly what they asked into the language they named, keeping technical terms as they are "
        "taught; add nothing else unless asked.",
    ),
    "simplify_text": Intent(
        "language",
        "Rewrite existing text in easier words, keeping its meaning",
        "Rewrite existing content in easier words while keeping its original meaning. Choose this when "
        "simplification is requested, not when the student asks to learn a concept from scratch. Example: “Is "
        "answer ko easy English mein likho.”",
        "Rewrite it in simpler words and shorter sentences for their class, keeping every fact and adding nothing new.",
    ),
    "answer_formatting": Intent(
        "language",
        "Change an answer's format, length, tone or exam style, not its meaning",
        "Change the format, length, tone, structure, or exam style of an existing or requested answer without "
        "changing its core meaning. Example: “Write this in 5 CBSE-style points.”",
        "Format it as they asked, or as a board-exam answer: points or short paragraphs, key terms in bold, and a "
        "length that fits the marks.",
    ),
    "generate_mcq": Intent(
        "tests",
        "Write a set of multiple-choice questions (MCQs), not an interactive quiz",
        "Create multiple-choice questions with answer options, usually with an answer key if requested. Choose "
        "when generating MCQs is the main task, not running an interactive question-by-question quiz. Example: "
        "“Give me 20 MCQs on acids and bases.”",
        "Give multiple-choice questions on what they named, with the number and difficulty they asked for.",
        bank=True,
    ),
    "conduct_quiz": Intent(
        "tests",
        "Run an interactive quiz, one question at a time",
        "Run an interactive quiz, typically asking one question at a time and responding to the student's "
        "answers. Example: “Ask me one question at a time.”",
        "Quiz them now on what they named, or on what this chat has covered.",
        bank=True,
    ),
    "mock_test": Intent(
        "tests",
        "Set a longer exam-like mock test with a duration, marks or sections",
        "Create or administer a longer, exam-like assessment with a defined duration, marks, or multiple "
        "sections. Example: “Take a 30-minute Science test.”",
        "Make it a full mock test: about 20 to 30 questions across the chapters they named (up to 3), mixed "
        "difficulty, unless they said otherwise.",
        bank=True,
    ),
    "exam_prep": Intent(
        "tests",
        "Help prepare for an exam: strategy, coverage or overall approach",
        "Help prepare for a named or upcoming exam through strategy, topic coverage, or an overall preparation "
        "approach. Use study_schedule when the primary request is a timetable. Example: “Boards ke liye 10 days "
        "bache hain.”",
        "Help them prepare for the exam: what to focus on, how to revise it and how to write answers, for their "
        "class, board and exam where known.",
    ),
    "important_topics": Intent(
        "tests",
        "Name the most important topics or chapters to focus on or revise",
        "Identify or prioritize topics, chapters, or concepts to focus on for revision or an exam. Do not claim a "
        "topic is guaranteed to appear. Example: “Which chapters should I revise first?”",
        "List the most important topics or question types, most important first, each with why it matters; never "
        "claim to know what the paper will contain.",
    ),
    "marking_rubric": Intent(
        "feedback",
        "Explain how an answer is marked: expected structure, points or marks",
        "Explain the expected structure, criteria, or mark allocation for an answer or task. Example: “What "
        "should a 5-mark answer contain?”",
        "Explain how such an answer is marked: the points or steps an examiner looks for and how marks are "
        "usually split; say so if their board's exact scheme isn't known.",
    ),
    "evaluate_written_answer": Intent(
        "feedback",
        "Assess the student's written answer and give feedback or marks",
        "Assess a student's written response against a prompt, rubric, or expected answer; provide feedback or "
        "marks if requested. Example: “Check my answer and give marks out of 5.”",
        "Evaluate it as a board examiner would: what earns marks, what is missing or wrong, how to improve it. "
        "Give a mark only if the question's marks are known; never invent a marking scheme.",
    ),
    "difficulty_adjustment": Intent(
        "tests",
        "Make questions, practice or explanations harder or easier",
        "Change the difficulty of existing or future questions, practice, or explanations. Example: “Ab thode "
        "difficult questions do.”",
        "Change the level as they asked (harder or easier) and keep the same topic; for a test, set a new one at "
        "that difficulty.",
        bank=True,
    ),
    "performance_analysis": Intent(
        "planning",
        "Analyse the student's own test results or progress: strengths, weaknesses",
        "Analyze completed quiz/test results or past performance to identify strengths, weaknesses and "
        "improvement areas. Example: “Which topics am I weak in?”",
        "Answer from the app's records in these instructions (practice record, this chat's practice tests, the "
        '"Learning so far" line) and quote them exactly. If there is no record of what they ask about, say so.',
        retrieval=False,
    ),
    "study_schedule": Intent(
        "planning",
        "Make a study timetable or schedule over a stated period",
        "Create a timetable or schedule with study sessions and time allocation over a stated period. Example: "
        "“Make a timetable for my next 7 days.”",
        "Make a realistic study plan as a table (days or weeks, subject or chapter, time, revision and practice), "
        "using their goals, study time, subjects, weak topics and revision due where given.",
        retrieval=False,
    ),
    "diagram_explanation": Intent(
        "visual_lab",
        "Explain a diagram: what it shows and how its parts work",
        "Explain what a supplied or clearly identified diagram represents and how its parts/process work. "
        "Example: “Explain this heart diagram.”",
        "Explain the diagram part by part and how the parts work together, from the reference passages or their "
        "description. You cannot see images: if it is unclear which diagram they mean, ask.",
    ),
    "diagram_labeling": Intent(
        "visual_lab",
        "Name or label the parts of a diagram",
        "Name, identify, or place labels on parts of a diagram. Example: “Label the parts of a flower.”",
        "Give the labels as a numbered list (label, then what it is) for the textbook diagram they mean. You "
        "cannot see images: if it is unclear which diagram, ask.",
    ),
    "graph_interpretation": Intent(
        "visual_lab",
        "Read or explain a graph or chart: values, trends, axes, conclusions",
        "Read or explain values, trends, axes, relationships, or conclusions from a graph or chart. Example: "
        "“What does this velocity-time graph show?”",
        "Read the graph from what they gave (data, axes, the attached file's text): each axis, the trend, key "
        "values and what it means; never invent values.",
    ),
    "image_question_solving": Intent(
        "visual_lab",
        "Answer a question in an uploaded image or photo (not a diagram or graph)",
        "Answer a question contained in an uploaded or supplied image when it is not more specifically a diagram "
        "explanation, diagram labeling, or graph interpretation task. Example: “Solve question 4 in this photo.”",
        "The question is in their attached file: work from its text, and restate the question in one line first. "
        "If the text is missing or unreadable, say so and ask them to type it.",
    ),
    "experiment_procedure": Intent(
        "visual_lab",
        "Explain how to do an experiment: materials, steps or method",
        "Explain the materials, steps, or method for carrying out a school experiment or practical. Example: “How "
        "do we test for starch in leaves?”",
        "Give the experiment as aim, materials, numbered steps, expected observations and result, with its "
        "precautions.",
    ),
    "observation_inference": Intent(
        "visual_lab",
        "Explain what an experiment's results or observations show",
        "Interpret experimental results or observations and explain what conclusion they support. Example: “Why "
        "did the solution turn blue-black?”",
        "For each observation, state what it shows and why it follows; keep observations and inferences separate.",
    ),
    "lab_safety": Intent(
        "visual_lab",
        "Explain lab safety: precautions, hazards and safe handling",
        "Explain safety precautions, hazards, or safe handling for a school laboratory activity. Example: “What "
        "safety precautions are needed here?”",
        "Give the safety precautions as a short list, most important first (hazards in a warning card), and "
        "remind them to follow their teacher's instructions.",
    ),
    "project_assignment": Intent(
        "visual_lab",
        "Help plan or prepare a school project or assignment",
        "Help plan or prepare a school project or assignment deliverable, such as sections, research plan, model, "
        "or presentation. Example: “Help me make a project on water conservation.”",
        "Help them plan and do it themselves: an outline, steps, materials and how to present it; write sections "
        "only when they ask.",
    ),
}

GROUP_MEMBERS: dict[str, tuple[str, ...]] = {
    group: tuple(name for name, intent in INTENTS.items() if intent.group == group)
    for group in GROUPS
    if group != ABSTAIN
}
BANK_INTENTS = frozenset(name for name, intent in INTENTS.items() if intent.bank)
