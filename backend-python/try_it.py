"""
try_it.py
---------
A quick LOCAL test so you can see the Ayurveda/Yoga AI working straight away,
WITHOUT needing Convex, the dashboard, or the tunnel.

Run it (after installing requirements and setting the keys in .env):
    python try_it.py

Repointed from the legacy LangGraph flow to `consult.run_turn` -- the same code
path the website uses -- when that flow was deleted. It was the last caller.
"""

import asyncio

from src.consult import run_turn


def main() -> None:
    print("=" * 55)
    print(" Ayurveda & Yoga Assistant - quick local test")
    print("=" * 55)
    print("Type your problem. It will ask a couple of questions, then plan.\n")

    # A simple example profile so the answer is personalised.
    profile = (
        "Age: 29\nGender: female\nFood preference: vegetarian\n"
        "Sleep: late\nWater intake: low\nStress: high"
    )

    message = input("Describe your problem: ").strip()
    context = None

    while True:
        result = asyncio.run(
            run_turn(
                problem=message if context is None else "",
                raw_context=context,
                answers=None,
                free_text=None if context is None else message,
                profile=profile,
            )
        )
        context = result.context.model_dump()

        print("\n" + "-" * 55)
        print(result.answer or "(no reply)")
        print("-" * 55)

        # `answer` is the plan; anything else is still gathering or chatting.
        if result.kind in ("answer", "escalation", "error"):
            break

        message = input("\nYour reply (blank to stop): ").strip()
        if not message:
            break


if __name__ == "__main__":
    main()
