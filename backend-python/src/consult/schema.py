"""
consult/schema.py
-----------------
The wire contract between the AI backend and the dashboard.

The whole point of the redesign lives here: instead of the model emitting one
free-text question per turn ("What did you eat?" -> user types), it emits an
`IntakePlan` — a set of questions with pre-written options the user simply clicks.

Deliberately only three question `type`s. Every extra type is another renderer,
another validator branch, and another way the model produces something the UI
cannot draw. A 1-5 severity scale is just `single` with `display="scale"`: same
data, different CSS.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Caps applied by the repair layer. Generous enough for any real condition,
# tight enough that a runaway model can't render 30 cards.
MAX_QUESTIONS = 6
MAX_OPTIONS = 8
MAX_LABEL = 90
MAX_OPTION_LABEL = 44
MAX_CONDITION = 60


class Option(BaseModel):
    """One clickable chip."""

    model_config = ConfigDict(extra="ignore")

    id: str
    label: str
    emoji: str | None = None
    # Set by the planner on answers that warrant seeing a doctor (e.g. "blood in
    # stool"). Selecting one escalates deterministically, instead of relying on
    # keyword matching against text the model invented.
    red_flag: bool = False


class Question(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    label: str
    hint: str | None = None
    type: Literal["single", "multi", "text"] = "single"
    # Rendering hint only — never affects validation or the prompt.
    display: Literal["chips", "scale", "cards"] = "chips"
    options: list[Option] = Field(default_factory=list)
    max_select: int | None = None
    # Everything is skippable. Forcing answers recreates the interrogation.
    required: bool = False


class IntakePlan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # Display label and retrieval hint ONLY. Nothing may branch on this value —
    # the moment `if condition == "acidity"` appears, per-disease flows are back.
    condition: str = ""
    note: str = ""
    questions: list[Question] = Field(default_factory=list)
    # Decided during round 1 so a second round costs no extra planning call.
    needs_second_round: bool = False


class Answer(BaseModel):
    """What the user picked for one question."""

    model_config = ConfigDict(extra="ignore")

    options: list[str] = Field(default_factory=list)  # option ids
    text: str | None = None


class ChatTurn(BaseModel):
    """One line of ordinary conversation, kept so replies follow on properly."""

    model_config = ConfigDict(extra="ignore")

    role: Literal["user", "assistant"]
    text: str


# Enough for the assistant to see how the conversation is going, without letting
# the context blob (which rides on every request) grow without bound.
#
# RAISED 10 -> 24. Since the intake cards were removed, this history IS the
# clinical record - write_plan is fed render_history(). At 10 turns, and with
# small talk sharing the window (remember_chat runs for greetings too), five
# throwaway replies were enough to push every clinical fact out of view:
#
#     after turn  5   duration, trigger, bloating, belching
#     after turn  8   duration GONE
#     after turn  9   trigger GONE
#     after turn 10   nothing left
#
# The plan was then written for a complaint whose details the model could no
# longer see. Raising the COUNT is the fix, and it is cheap, because real user
# messages are tiny - measured at 2-59 chars, median 23:
#
#     10 turns    779 tokens        24 turns   1870 tokens   (+1091)
#
# ~1091 extra input tokens is less than one knowledge note (1501 avg).
#
# Deliberately NOT raising state.MAX_NOTE_CHARS (400). Measured: it never fires
# on user turns, and rework_answer reads `last_answer` (6000 chars), not this
# history - so the assistant entries here only carry conversational continuity,
# which 400 covers. Raising it to 800 would cost 3609 tokens for no benefit.
MAX_CHAT_HISTORY = 24

# The conversation state machine.
#
#   idle       nothing said yet
#   greeted    hello exchanged — do NOT greet again
#   casual     chatting, no health concern raised
#   gathering  asking about the complaint IN PROSE, one or two questions a turn
#   completed  plan delivered
#
# Transitions:
#   idle/greeted/casual/completed --(typed message)--> routed by intent
#   any --(health intent)--> gathering
#   gathering --(enough detail)--> completed (the plan)
#   any --(red flag)--> completed (escalation)
#
# RETIRED, BUT STILL ACCEPTED:
#   collecting  answering generated question CARDS
#   choosing    picking which parts of the plan they want
#
# Both are gone from the product — the consultation is a conversation now — but
# they MUST stay in this Literal. `state.load_context` returns a FRESH context
# whenever validation raises, so narrowing this would silently reset every
# conversation that is mid-intake at deploy time: the user's half-finished
# consultation would vanish and the assistant would greet them again. They are
# mapped to `gathering` on load instead. Remove them only once no persisted blob
# can still carry one.
Phase = Literal[
    "idle", "greeted", "casual", "gathering", "asking_focus",
    "collecting", "choosing", "completed"
]

# Phases retired in the move to conversational gathering, mapped on load.
LEGACY_PHASES = ("collecting", "choosing")

# States where a typed message is the ongoing consultation rather than a new
# message to be routed. The legacy two are kept so a conversation persisted
# before the change keeps behaving correctly on its next turn.
CONSULTING = ("gathering", "collecting", "choosing")


class PatientProfile(BaseModel):
    """The long-lived clinical facts about a person, as THEY stated them.

    USER-STATED FACTS ONLY. Nothing the model infers may be written here — not
    a guessed diagnosis, not an Ayurveda interpretation, not a causal
    assumption. "I have kidney disease" belongs here; "kidney disease is
    causing the acidity" never does, because that is interpretation and the
    next consultation would read it back as though the patient had said it.
    The rule is kept structurally rather than by a provenance tag: the
    extraction step returns only what was said, and `state.merge_profile`
    writes only these keys.

    Split deliberately from the consultation's own state. `symptoms`,
    `condition` and `missing_info` describe THIS complaint and are meant to be
    thrown away; everything here outlives it. Today's nausea is not a
    long-term fact about a person, and storing it as one would have the
    assistant asking about it months later.

    `supplements` is separate from `medications` on purpose: SYSTEM_RULES
    rule 2 treats a prescribed drug and a herb very differently, and the
    safety check before suggesting anything needs to tell them apart.

    Every list is bounded by `state.merge_profile` — this rides on every
    request and is persisted per user, so it cannot be allowed to grow without
    limit.
    """

    model_config = ConfigDict(extra="ignore")

    age: str = ""
    sex: str = ""
    occupation: str = ""
    lifestyle: list[str] = Field(default_factory=list)
    # Diagnosed conditions only, never a suspicion.
    conditions: list[str] = Field(default_factory=list)
    medications: list[str] = Field(default_factory=list)
    supplements: list[str] = Field(default_factory=list)
    allergies: list[str] = Field(default_factory=list)
    surgeries: list[str] = Field(default_factory=list)
    family_history: list[str] = Field(default_factory=list)
    # Asked only when the complaint or the profile makes it relevant.
    reproductive: str = ""
    updated_at: str = ""

    def is_empty(self) -> bool:
        """Nothing known yet — the caller has never told us anything."""
        return not any(
            (
                self.age, self.sex, self.occupation, self.reproductive,
                self.lifestyle, self.conditions, self.medications,
                self.supplements, self.allergies, self.surgeries,
                self.family_history,
            )
        )


class ConsultContext(BaseModel):
    """Session state the client echoes back each turn.

    Carries CONVERSATION state only — what was said in this chat and how far the
    intake has got. The user's medical profile, past consultations and uploaded
    reports are server-owned and fetched by the retrieval layer; they are never
    accepted from the browser.
    """

    model_config = ConfigDict(extra="ignore")

    # Bumped when the shape changes; an unknown version is discarded rather than
    # crashing on an old blob persisted in Convex. v2 added the state machine and
    # chat history.
    v: int = 2
    phase: Phase = "idle"
    # True once a greeting has been exchanged, so the assistant never opens with
    # "Namaste! How can I help?" twice in the same conversation.
    greeted: bool = False
    # Recent turns of ordinary conversation, so replies respond to what was
    # actually said instead of restarting every message. Each turn is truncated.
    chat_history: list[ChatTurn] = Field(default_factory=list)
    # The last substantial answer, kept in FULL. `chat_history` truncates every
    # turn, which is fine for "what were we talking about" but useless for
    # "translate that into English" — a faithful rewrite needs the whole text.
    last_answer: str = ""
    # The language the conversation settled into: "english", "hinglish" or
    # "devanagari". Sticky ON PURPOSE. Detecting per message looked reasonable
    # until a follow-up carried no signal of its own — "tell me more" has no
    # Hindi function words, so an English conversation silently flipped to
    # Hinglish on the very next turn. Set once from the first real message, and
    # changed only when the user actually asks for another language.
    language: str = ""
    round: int = 0
    problem: str = ""
    condition: str = ""
    needs_second_round: bool = False
    # Plans already issued, so submitted option ids can be resolved to labels
    # server-side. Answers are keyed by question id, so re-answering overwrites.
    asked: list[Question] = Field(default_factory=list)
    answers: dict[str, Answer] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    # SHORT retrieval keywords accumulated while gathering — "gas", "after
    # meals", "spicy food". Never sentences.
    #
    # This is what replaced the tapped option labels as the retrieval signal, and
    # the shortness is the whole point. `state.search_query` builds the vector
    # query from these, and its docstring records the measurement: appending the
    # full collected text dropped an acidity query from 0.408 to 0.172, enough to
    # start losing notes that genuinely match. Feeding the transcript here would
    # reproduce exactly that.
    #
    # New in the conversational flow; absent from every older persisted blob,
    # which is why it defaults empty rather than bumping the version.
    symptoms: list[str] = Field(default_factory=list)
    # What gathering still doesn't know, refreshed each turn — makes the
    # model's already-implicit "what's missing" reasoning an observable piece
    # of state, same short-keyword discipline as `symptoms`. Same
    # no-version-bump precedent: absent from older blobs, defaults empty.
    missing_info: list[str] = Field(default_factory=list)
    # Which of the six sections they actually want, chosen conversationally
    # once gathering is ready (phase="asking_focus") rather than from a card
    # menu — see `classify_focus` in gathering.py and `_HELP_TYPE_SECTIONS`
    # in graph.py. "" before it's been asked/answered; one of root_cause,
    # remedies, yoga, diet, complete afterward.
    #
    # KEPT AS A STRING ON PURPOSE, and still populated, even though
    # `help_types` below is now the authoritative field. `state.load_context`
    # returns a FRESH context whenever validation raises, so widening this to
    # a list would silently reset every conversation that is mid-flow at
    # deploy time, carrying `help_type: "complete"` from the old shape — the
    # same trap LEGACY_PHASES exists to avoid. Readers should prefer
    # `help_types` and fall back to this.
    help_type: str = ""
    # EVERY focus they asked for, not just the first. "root cause and complete
    # plan both" and "yoga and diet" are both ordinary answers to the focus
    # question, and collapsing them to one value silently dropped half of what
    # was asked — "yoga and diet" became `complete` (all six sections) rather
    # than the two requested. Empty before the focus question is answered.
    #
    # New field with a default rather than a version bump, the same
    # no-migration precedent `symptoms`, `missing_info` and `help_type` each
    # already use: absent from older persisted blobs, defaults empty.
    help_types: list[str] = Field(default_factory=list)
    # HAS THIS CONVERSATION HIT A RED FLAG? "" or "urgent".
    #
    # Risk used to be recomputed from scratch every turn by re-scanning the
    # transcript (`state.safety_fragments`), and that lost the exact case it
    # most needed to hold. Measured against production:
    #
    #   "I am vomiting 5+ times a day and I cannot keep fluids down"
    #       -> escalation, correctly
    #   "Can you tell me some yoga?"
    #       -> a full sectioned plan
    #
    # The first turn escalated on `gathered.red_flag` — the MODEL's judgement,
    # not the keyword scan, because `safety.RED_FLAG_KEYWORDS` holds phrases
    # ("ulti me khoon") and matches nothing in that sentence. `red_flag` is a
    # per-turn transient, so by the next turn nothing remembered, `phase`
    # was "completed" (which skips gathering), and the turn fell through to
    # write_plan.
    #
    # The transcript mechanism has three more holes this closes: escalations
    # raised without `said` record nothing at all; MAX_CHAT_HISTORY evicts the
    # triggering sentence after 24 turns; and remember_chat truncates a turn
    # at 400 chars.
    #
    # STICKY ON PURPOSE. Nothing sets this back to "". Once a conversation has
    # shown a red flag there is no wellness answer that becomes appropriate
    # again three messages later — the same reasoning `_escalate` already
    # documents for re-escalating on every following turn.
    risk_level: str = ""
    # Short label of what tripped it, so the reply can explain itself in
    # natural language instead of repeating a fixed string.
    risk_reason: str = ""
    # The long-lived clinical facts, loaded once per conversation from Convex
    # and merged as the person says more. See `PatientProfile`.
    #
    # It rides in the context rather than being re-fetched per turn because
    # the client already round-trips this blob and Convex already persists it
    # (`consults.state`), so one load per conversation is all that is needed.
    patient_profile: PatientProfile = Field(default_factory=PatientProfile)
    # Whether the load has been attempted for this conversation. Separate from
    # "is the profile empty", because a genuinely empty profile must not cause
    # a refetch on every single turn.
    profile_loaded: bool = False
    # A serious diagnosed condition this person has disclosed, e.g. "cancer".
    #
    # Set ONCE, when it is first detected. Before this existed the serious
    # branch re-derived the condition from the transcript on every turn and so
    # re-fired forever: the user answered "AML, on chemotherapy" and received
    # another supportive-care paragraph instead of a follow-up question, and
    # no detail was ever collected. Holding it here lets the deep-dive run as
    # a conversation — see `prompts.GATHERING_PROMPT`'s serious-condition mode.
    serious_condition: str = ""


class ConsultResult(BaseModel):
    """One turn's response."""

    model_config = ConfigDict(extra="ignore")

    # chat  = a conversational reply (greeting, "what can you do", an off-topic
    #         question, or a general Ayurveda question) with no cards attached.
    # error = the assistant could not run at all — quota exhausted, bad key,
    #         provider down. Rendered as a warning, not as something the
    #         assistant "said", so the user knows to retry rather than rephrase.
    kind: Literal["chat", "intake", "answer", "escalation", "error"]
    condition: str = ""
    message: str = ""
    intake: IntakePlan | None = None
    answer: str = ""
    context: ConsultContext = Field(default_factory=ConsultContext)
    sources: list[dict] = Field(default_factory=list)
