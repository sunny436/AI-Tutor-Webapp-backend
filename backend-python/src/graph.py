"""
graph.py
--------
This is the BRAIN of the product, built with LangGraph.

LangGraph lets us design the conversation as a small set of steps ("nodes")
with branches. Our flow:

    safety check ── emergency? ──yes──► return "see a doctor" message
        │ no
        ▼
    do we have enough info? ──no──► return ONE follow-up question
        │ yes
        ▼
    search Ayurveda/Yoga knowledge (RAG)
        ▼
    write the full solution (root cause + changes + food chart + routine)

The "keep asking until we have enough info" LOOP happens naturally across
messages: each time the user replies, the whole conversation is sent again,
and this graph decides whether to ask another question or to answer.
"""

import json
from typing import TypedDict

from langgraph.graph import StateGraph, START, END
from langchain_core.messages import SystemMessage, HumanMessage

import config
from src.llm import get_llm
from src import prompts, safety
from src.knowledge import search_knowledge


# ---- The "memory" that flows through the steps ----
class ConsultState(TypedDict):
    problem: str        # what the user is facing
    profile: str        # the user's health profile (as text)
    history: str        # the conversation / details collected so far
    notes: str          # anything already noted
    followups: int      # how many follow-up questions we've asked already
    knowledge: str      # Ayurveda/Yoga notes found by search
    route: str          # which way to go next
    kind: str           # "escalation" | "followup" | "answer"
    answer: str         # the text we send back to the user


def _extract_json(text: str) -> dict:
    """Pull the JSON object out of the model's reply, safely."""
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        return json.loads(text[start:end])
    except Exception:
        # If parsing fails, assume we have enough info and just answer.
        return {"enough": True, "question": ""}


# ---- Node 1: safety check ----
def safety_node(state: ConsultState) -> dict:
    text = f"{state['problem']} {state['history']}"
    if safety.is_emergency(text):
        return {
            "kind": "escalation",
            "answer": safety.ESCALATION_MESSAGE,
            "route": "end",
        }
    return {"route": "gather"}


# ---- Node 2: decide if we have enough info ----
def gather_node(state: ConsultState) -> dict:
    # Safety valve: never ask more than MAX_FOLLOWUPS questions.
    if state["followups"] >= config.MAX_FOLLOWUPS:
        return {"route": "retrieve"}

    llm = get_llm(temperature=0.2)
    prompt = prompts.GATHER_DECISION_PROMPT.format(
        profile=state["profile"],
        history=state["history"],
        notes=state["notes"],
    )
    reply = llm.invoke([HumanMessage(content=prompt)]).content
    decision = _extract_json(reply)

    if not decision.get("enough", True) and decision.get("question"):
        return {
            "kind": "followup",
            "answer": decision["question"],
            "route": "end",
        }
    return {"route": "retrieve"}


# ---- Node 3: search the Ayurveda/Yoga knowledge ----
def retrieve_node(state: ConsultState) -> dict:
    query = f"{state['problem']} {state['history']}"
    knowledge = search_knowledge(query, k=4)
    return {"knowledge": knowledge, "route": "answer"}


# ---- Node 4: write the full solution ----
def answer_node(state: ConsultState) -> dict:
    llm = get_llm(temperature=0.5)
    prompt = prompts.ANSWER_PROMPT.format(
        system_rules=prompts.SYSTEM_RULES,
        knowledge=state["knowledge"] or "(no extra notes found)",
        profile=state["profile"],
        history=f"Problem: {state['problem']}\n{state['history']}",
    )
    answer = llm.invoke([
        SystemMessage(content=prompts.SYSTEM_RULES),
        HumanMessage(content=prompt),
    ]).content
    return {"kind": "answer", "answer": answer, "route": "end"}


# ---- Router helpers (decide the next node from state['route']) ----
def _after_safety(state: ConsultState) -> str:
    return END if state["route"] == "end" else "gather"


def _after_gather(state: ConsultState) -> str:
    return END if state["route"] == "end" else "retrieve"


def build_graph():
    """Wire the nodes together into a runnable graph."""
    g = StateGraph(ConsultState)
    g.add_node("safety", safety_node)
    g.add_node("gather", gather_node)
    g.add_node("retrieve", retrieve_node)
    g.add_node("answer", answer_node)

    g.add_edge(START, "safety")
    g.add_conditional_edges("safety", _after_safety, {"gather": "gather", END: END})
    g.add_conditional_edges("gather", _after_gather, {"retrieve": "retrieve", END: END})
    g.add_edge("retrieve", "answer")
    g.add_edge("answer", END)
    return g.compile()


# Build the graph once when this module is imported (reused for every request).
GRAPH = build_graph()


def run_consult(problem: str, profile: str, history: str, followups: int = 0) -> dict:
    """
    Run one turn of the flow.

    Returns a dict:
      {
        "kind": "escalation" | "followup" | "answer",
        "answer": "<text to show the user>",
        "knowledge_used": "<the notes the AI used, for transparency>"
      }
    """
    initial: ConsultState = {
        "problem": problem,
        "profile": profile or "No profile provided.",
        "history": history or "",
        "notes": "",
        "followups": followups,
        "knowledge": "",
        "route": "",
        "kind": "",
        "answer": "",
    }
    final = GRAPH.invoke(initial)
    return {
        "kind": final.get("kind", "answer"),
        "answer": final.get("answer", ""),
        "knowledge_used": final.get("knowledge", ""),
    }
