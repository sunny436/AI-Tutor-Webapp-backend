"""
try_it.py
---------
A quick LOCAL test so you can see the assistant working straight away,
WITHOUT needing Convex, the dashboard, or the tunnel.

Run it (after installing requirements and setting GRAPHRAG_* in .env):
    python try_it.py

Exercises exactly what server.py does for one turn: the safety scan, then
GraphRAG's own /v1/answer. There is no local model and no local knowledge
base to test — GraphRAG's team owns retrieval and answer quality now.
"""

import config
from src import graphrag, safety


def main() -> None:
    print("=" * 55)
    print(" Ayurveda & Yoga Assistant - quick local test")
    print("=" * 55)

    if not config.is_graphrag_ready():
        print("GRAPHRAG_ENABLED, GRAPHRAG_BASE_URL and GRAPHRAG_API_KEY must all be")
        print("set in .env before this can answer anything.")
        return

    message = input("Describe your problem: ").strip()
    if not message:
        return

    if safety.scan(message):
        print("\n" + "-" * 55)
        print(safety.ESCALATION_MESSAGE)
        print("-" * 55)
        return

    if safety.is_serious_condition(message):
        print("\n" + "-" * 55)
        print(safety.SERIOUS_CONDITION_MESSAGE)
        print("-" * 55)
        return

    print("\nAsking GraphRAG...")
    try:
        body = graphrag.answer(message)
    except Exception as error:  # noqa: BLE001
        print(f"GraphRAG could not answer: {error}")
        return

    print("\n" + "-" * 55)
    print(body.get("answer") or "(no reply)")
    print("-" * 55)


if __name__ == "__main__":
    main()
