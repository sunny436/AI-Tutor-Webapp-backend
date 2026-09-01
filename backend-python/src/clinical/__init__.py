"""
src/clinical/
-------------
The clinical reasoning layer that sits between the conversation and the answer.

WHY A NEW PACKAGE RATHER THAN MORE OF `src/consult/`
`consult/` owns the CONVERSATION: routing a message, asking the next question,
choosing sections, writing prose. What goes here owns the PATIENT: what is true
about them, which problem they are talking about, how urgent it is, what may
safely be recommended. The two have different lifetimes — a consultation is
thrown away, a patient is not — and mixing them is what produced a 1,400-line
`graph.py` that has to be read end to end before any of it can be changed.

Every module here is importable and testable on its own, takes plain data and
returns plain data, and does no I/O of its own. `consult/graph.py` remains the
only orchestrator; these are the things it calls.

STAGES ARE SEPARATE EVEN WHERE CALLS ARE SHARED. Several of these modules are
answered by ONE structured LLM call for latency (a turn already costs 40-60s
with the calls that exist today), but each keeps its own schema and its own
tests, so a stage can later move to its own model without the callers changing.
"""
