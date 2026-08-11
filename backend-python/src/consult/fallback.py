"""
consult/fallback.py
-------------------
The safety net for a failed first planning call.

If the model returns unusable JSON on round 1 and the retry also fails, the user
would otherwise be looking at an empty screen with nothing to click. This one
generic plan fires instead.

It is NOT a per-disease flow — that is exactly what the redesign removes. It is a
single condition-agnostic set of questions that applies to essentially any
complaint, and the user cannot tell the difference. Every real plan still comes
from the model.

WHY IT IS TRANSLATED IN CODE
This used to be English only, on the reasoning that it fires perhaps once in
fifty turns. Both halves of that turned out to be wrong.

It fired on most Devanagari consultations, because a Hindi intake form did not
fit in the planner's token budget (see MAX_TOKENS_PLANNER in config.py) and the
truncated JSON failed to parse. So the users most likely to see this form were
exactly the ones who could not read it: somebody wrote "मुझे गैस की समस्या है"
and got back "How long has this been going on?".

The budget is fixed, so this should now be rare again. It is translated anyway,
because a fallback that only works in one language is not a fallback — and the
translation is a table, not a model call, which matters: this path exists
precisely because the model just failed. Asking it to translate here would be
asking the broken thing to fix itself.
"""

from __future__ import annotations

from src.consult.schema import IntakePlan, Option, Question

# Question and option ids are IDENTICAL across languages on purpose. Only the
# text a human reads changes; everything downstream — answer resolution, safety
# scanning, the summary — keys off the ids and is unaffected by the language.
_EMOJI = {
    "today": "🕐", "few_days": "📅", "weeks": "🗓️", "months": "⏳",
    "mild": "🙂", "moderate": "😐", "severe": "😣",
    "morning": "🌅", "after_food": "🍽️", "evening": "🌆", "night": "🌙",
    "normal": "✅", "bloating": "🎈", "constipation": "🚫", "loose": "💧",
    "acidity": "🔥",
    "sleep_poor": "😴", "sleep_ok": "🛌", "stress_high": "😰", "stress_low": "🧘",
}

# language -> {"note", "labels": {question_id: text}, "options": {option_id: text},
#              "hint"}
_TEXT: dict[str, dict] = {
    "english": {
        "note": "Tell me a little more so I can give you an accurate plan.",
        "hint": "Optional",
        "labels": {
            "duration": "How long has this been going on?",
            "severity": "How much is it affecting your day?",
            "timing": "When is it usually worst?",
            "digestion": "How is your digestion?",
            "sleep_stress": "How are your sleep and stress lately?",
            "anything_else": "Anything else I should know?",
        },
        "options": {
            "today": "Just today", "few_days": "A few days",
            "weeks": "A few weeks", "months": "Months or longer",
            "mild": "Mild", "moderate": "Moderate", "severe": "Severe",
            "morning": "Morning", "after_food": "After eating",
            "evening": "Evening", "night": "Night",
            "normal": "Normal", "bloating": "Bloating",
            "constipation": "Constipation", "loose": "Loose motions",
            "acidity": "Acidity",
            "sleep_poor": "Sleeping poorly", "sleep_ok": "Sleeping well",
            "stress_high": "High stress", "stress_low": "Low stress",
        },
    },
    "hinglish": {
        "note": "Thoda aur bataiye taaki main aapko sahi plan de sakun.",
        "hint": "Optional",
        "labels": {
            "duration": "Yeh kitne time se ho raha hai?",
            "severity": "Aapke din par kitna asar padta hai?",
            "timing": "Kab sabse zyada hota hai?",
            "digestion": "Aapka pachan kaisa hai?",
            "sleep_stress": "Aajkal neend aur stress kaisa hai?",
            "anything_else": "Aur kuch bataana chahenge?",
        },
        "options": {
            "today": "Aaj hi se", "few_days": "Kuch din se",
            "weeks": "Kuch hafte se", "months": "Mahino se ya zyada",
            "mild": "Halka", "moderate": "Madhyam", "severe": "Tez",
            "morning": "Subah", "after_food": "Khane ke baad",
            "evening": "Shaam", "night": "Raat",
            "normal": "Theek hai", "bloating": "Pet phoolna",
            "constipation": "Kabz", "loose": "Loose motion",
            "acidity": "Acidity",
            "sleep_poor": "Neend theek nahi", "sleep_ok": "Neend acchi hai",
            "stress_high": "Zyada stress", "stress_low": "Kam stress",
        },
    },
    "devanagari": {
        "note": "थोड़ा और बताइए ताकि मैं आपको सही सलाह दे सकूँ।",
        "hint": "वैकल्पिक",
        "labels": {
            "duration": "यह कितने समय से हो रहा है?",
            "severity": "आपके दिन पर कितना असर पड़ता है?",
            "timing": "यह सबसे ज़्यादा कब होता है?",
            "digestion": "आपका पाचन कैसा है?",
            "sleep_stress": "आजकल नींद और तनाव कैसा है?",
            "anything_else": "और कुछ बताना चाहेंगे?",
        },
        "options": {
            "today": "आज से", "few_days": "कुछ दिनों से",
            "weeks": "कुछ हफ़्तों से", "months": "महीनों या उससे ज़्यादा",
            "mild": "हल्का", "moderate": "मध्यम", "severe": "तेज़",
            "morning": "सुबह", "after_food": "खाने के बाद",
            "evening": "शाम", "night": "रात",
            "normal": "ठीक है", "bloating": "पेट फूलना",
            "constipation": "कब्ज़", "loose": "पतले दस्त",
            "acidity": "अम्लता",
            "sleep_poor": "नींद ठीक नहीं", "sleep_ok": "नींद अच्छी है",
            "stress_high": "ज़्यादा तनाव", "stress_low": "कम तनाव",
        },
    },
}

# question id -> (type, display, [option ids])
_SHAPE: list[tuple[str, str, str, list[str]]] = [
    ("duration", "single", "chips", ["today", "few_days", "weeks", "months"]),
    ("severity", "single", "scale", ["mild", "moderate", "severe"]),
    ("timing", "multi", "chips", ["morning", "after_food", "evening", "night"]),
    ("digestion", "multi", "chips", ["normal", "bloating", "constipation", "loose", "acidity"]),
    ("sleep_stress", "multi", "chips", ["sleep_poor", "sleep_ok", "stress_high", "stress_low"]),
]


def baseline_plan(condition: str = "", language: str = "") -> IntakePlan:
    """A universal intake used only when planning fails.

    Falls back to English for an unknown or empty language, which is the same
    behaviour this function had before it could speak anything else.
    """
    text = _TEXT.get((language or "").strip().lower(), _TEXT["english"])
    labels, options = text["labels"], text["options"]

    questions = [
        Question(
            id=qid,
            label=labels[qid],
            type=qtype,
            display=display,
            options=[
                Option(id=oid, label=options[oid], emoji=_EMOJI[oid]) for oid in option_ids
            ],
        )
        for qid, qtype, display, option_ids in _SHAPE
    ]
    questions.append(
        Question(
            id="anything_else",
            label=labels["anything_else"],
            hint=text["hint"],
            type="text",
        )
    )

    return IntakePlan(condition=condition, note=text["note"], questions=questions)
