"""
try_it.py
---------
A quick LOCAL test so you can see the Ayurveda/Yoga AI working straight away,
WITHOUT needing Convex, the dashboard, or ngrok.

Run it (after installing requirements and setting GROQ_API_KEY in .env):
    python try_it.py
"""

from src.graph import run_consult


def main():
    print("=" * 55)
    print(" Ayurveda & Yoga Assistant - quick local test")
    print("=" * 55)
    print("Type your problem, then answer any follow-up questions.\n")

    problem = input("Describe your problem: ").strip()

    # A simple example profile so the answer is personalized.
    profile = "Age: 29\nGender: female\nFood preference: vegetarian\nSleep: late\nWater intake: low\nStress: high"

    history = ""
    followups = 0

    while True:
        result = run_consult(problem, profile, history, followups)

        if result["kind"] == "followup":
            print("\nAssistant asks:", result["answer"])
            answer = input("Your answer: ").strip()
            history += f"\nAssistant asked: {result['answer']}\nUser answered: {answer}"
            followups += 1
            continue

        # Final answer or emergency escalation
        print("\n" + "-" * 55)
        print(result["answer"])
        print("-" * 55)
        break


if __name__ == "__main__":
    main()
