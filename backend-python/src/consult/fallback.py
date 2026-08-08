"""
consult/fallback.py
-------------------
The safety net for a failed first planning call.

If the model returns unusable JSON on round 1 and the retry also fails, the user
would otherwise be looking at an empty screen with nothing to click. This one
generic plan fires instead.

It is NOT a per-disease flow — that is exactly what the redesign removes. It is a
single condition-agnostic set of questions that applies to essentially any
complaint, used perhaps once in fifty turns, and the user cannot tell the
difference. Every real plan still comes from the model.
"""

from __future__ import annotations

from src.consult.schema import IntakePlan, Option, Question


def _options(*pairs: tuple[str, str, str]) -> list[Option]:
    return [Option(id=oid, label=label, emoji=emoji) for oid, label, emoji in pairs]


def baseline_plan(condition: str = "") -> IntakePlan:
    """A universal intake used only when planning fails."""
    return IntakePlan(
        condition=condition,
        note="Tell me a little more so I can give you an accurate plan.",
        questions=[
            Question(
                id="duration",
                label="How long has this been going on?",
                type="single",
                display="chips",
                options=_options(
                    ("today", "Just today", "🕐"),
                    ("few_days", "A few days", "📅"),
                    ("weeks", "A few weeks", "🗓️"),
                    ("months", "Months or longer", "⏳"),
                ),
            ),
            Question(
                id="severity",
                label="How much is it affecting your day?",
                type="single",
                display="scale",
                options=_options(
                    ("mild", "Mild", "🙂"),
                    ("moderate", "Moderate", "😐"),
                    ("severe", "Severe", "😣"),
                ),
            ),
            Question(
                id="timing",
                label="When is it usually worst?",
                type="multi",
                display="chips",
                options=_options(
                    ("morning", "Morning", "🌅"),
                    ("after_food", "After eating", "🍽️"),
                    ("evening", "Evening", "🌆"),
                    ("night", "Night", "🌙"),
                ),
            ),
            Question(
                id="digestion",
                label="How is your digestion?",
                type="multi",
                display="chips",
                options=_options(
                    ("normal", "Normal", "✅"),
                    ("bloating", "Bloating", "🎈"),
                    ("constipation", "Constipation", "🚫"),
                    ("loose", "Loose motions", "💧"),
                    ("acidity", "Acidity", "🔥"),
                ),
            ),
            Question(
                id="sleep_stress",
                label="How are your sleep and stress lately?",
                type="multi",
                display="chips",
                options=_options(
                    ("sleep_poor", "Sleeping poorly", "😴"),
                    ("sleep_ok", "Sleeping well", "🛌"),
                    ("stress_high", "High stress", "😰"),
                    ("stress_low", "Low stress", "🧘"),
                ),
            ),
            Question(
                id="anything_else",
                label="Anything else I should know?",
                hint="Optional",
                type="text",
            ),
        ],
    )
