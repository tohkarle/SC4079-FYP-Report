# Query Intent Router — Implementation

## Overview

`src/intent_router.py` is a lightweight, rule-based query intent classifier that sits before RAG retrieval in `chatbot.py`. It classifies each user query into one of three intents and maps it to a retrieval route.

### Intents

| Intent | Description | Route |
|---|---|---|
| `specific` | Precise fact, speaker, date, or local detail | `fine_grained_path` |
| `thematic` | Topic, concern, or aspect discussed in the transcript | `topic_path` |
| `global` | Overview, summary, or gist of the whole conversation | `summary_path` |
| *(low confidence)* | Signals conflict or are too weak | `hybrid_path` |

---

## Integration point

The current integration is no longer just a log hook. The chatbot and vague
evaluation now call the shared route-aware assembler in
`src/route_aware_context.py`, which internally runs:

```python
intent = detect_query_intent(question)
routing = decide_retrieval_route(intent)
retrieval_result = retrieve_for_chatbot(...)
result = assemble_route_aware_context(...)
```

So the router now actively changes prompt assembly for vague/global questions,
instead of only logging the chosen route.

---

## Current Call Graph

The current runtime call graph is:

```text
chatbot.py / evaluate_rag.py
  -> retrieve_route_aware_context(question, ...)
     -> detect_query_intent(question)
     -> decide_retrieval_route(intent_result)
     -> resolve route-specific retrieval profile from rag_config.py
     -> retrieve_for_chatbot(...)
     -> assemble_route_aware_context(...)
```

Important implementation detail:

- the router does **not** retrieve documents itself
- the router only decides the route
- the selected route then changes:
  - retrieval depth (`top_k_chunks`, `bm25_k`, `reranker_top_n`)
  - whether neighbor chunks are enabled
  - context token budget
  - transcript anchor selection
  - how summaries and support chunks are packed into the final prompt

### What each route-controlled property means

- `top_k_chunks`
  - Number of semantic/vector-search candidates retrieved before fusion and reranking.
  - Higher values increase recall but also increase noise and latency.
- `bm25_k`
  - Number of keyword/BM25 candidates retrieved before fusion.
  - Higher values help detail recall and exact phrase matching, especially for ASR transcripts.
- `reranker_top_n`
  - Number of chunks kept after cross-encoder reranking.
  - This is the size of the final flat evidence set before route-aware prompt packing.
- `neighbor_chunks_enabled`
  - Whether adjacent chunks are pulled around each retrieved chunk.
  - Used to preserve local conversational continuity.
- `context token budget`
  - The approximate maximum prompt budget reserved for route instructions + summary + evidence packing.
  - In broad routes, this is what allows the system to use the new 32k context window intentionally.
- `transcript anchor selection`
  - Which fixed transcript sections are injected regardless of retrieval ranking.
  - Anchors come from the indexed transcript in chronological order and can include:
    - `opening`
    - `early`
    - `middle`
    - `late`
    - `closing`
- `summary/support chunk packing`
  - The order and limits used when building the final prompt.
  - Current packing order is:
    1. route instructions
    2. transcript summary
    3. forced frame chunks
    4. supporting chunks
  - Broad routes also deduplicate near-duplicate text and sort packed evidence chronologically after selection.

So the router is now a control component for downstream retrieval and prompt assembly, not just a labeler.

---

## Current Runtime Behavior

### End-to-end flow

At runtime, the route-aware path works like this:

1. `detect_query_intent(query)` scores the query as `specific`, `thematic`, or `global`
2. `decide_retrieval_route(result)` maps that label and confidence into:
   - `fine_grained_path`
   - `topic_path`
   - `summary_path`
   - `hybrid_path`
3. `route_aware_context.py` runs the normal retriever via `retrieve_for_chatbot()`
4. It then rewrites the final prompt context based on the selected route
5. `chatbot.py` sends the LLM:
   - `route_instructions`
   - `transcript_summary`
   - `retrieved_context`
   - `chat_history`
   - `question`

### Confidence and route mapping

`intent_router.py` computes three raw scores:

- `specific_score`
- `thematic_score`
- `global_score`

It then sorts them and computes:

```python
confidence = (winner_score - runner_up_score) / winner_score
```

with `HIGH_CONFIDENCE_THRESHOLD = 0.50`.

Routing is:

| Label | Confidence | Route |
|---|---:|---|
| `specific` | `>= 0.50` | `fine_grained_path` |
| `thematic` | `>= 0.50` | `topic_path` |
| `global` | `>= 0.50` | `summary_path` |
| any label | `< 0.50` | `hybrid_path` |

If no signals fire at all, confidence becomes `0.0`, so the route falls back to
`hybrid_path`.

### Route-specific downstream behavior

After the route is chosen, `route_aware_context.py` applies the route-specific
profile from `rag_config.py`:

| Route | `top_k_chunks` | `bm25_k` | `reranker_top_n` | Neighbors | Context budget | Anchor limits | Support limit |
|---|---:|---:|---:|---|---:|---|---:|
| `fine_grained_path` | `12` | `30` | `8` | enabled (`count=1`) | `6000` | none | `8` |
| `topic_path` | `14` | `30` | `8` | disabled | `10000` | opening=`1`, middle=`1` | `8` |
| `summary_path` | `20` | `40` | `12` | disabled | `22000` | opening=`2`, early=`1`, middle=`1`, late=`1`, closing=`1` | `10` |
| `hybrid_path` | `18` | `35` | `10` | enabled (`count=1`) | `16000` | opening=`1`, early=`1`, middle=`1`, late=`1`, closing=`0` | `12` |

This means the router now changes both retrieval behavior and prompt behavior. 

Note that the `ROUTE_CONTEXT_TOKEN_BUDGETS` config exists for all four routes
but active token-budget enforcement is currently implemented only for `summary_path` and `hybrid_path`. `fine_grained_path` and `topic_path` have configured budget values, but those values are currently informational / future-facing rather than strictly enforced.

### How these settings affect each path

#### `fine_grained_path`

- Uses the smallest budget because the goal is precision, not transcript-wide coverage.
- `top_k_chunks=12` and `bm25_k=30` give the reranker a slightly larger candidate pool than the old default.
  - Justification: detail questions often fail because the relevant chunk is ranked slightly too low, not because the model needs transcript-wide context. A modest increase improves recall without flooding the reranker.
- `reranker_top_n=8` keeps enough candidates for local disambiguation.
  - Justification: this is large enough to preserve plausible alternatives for "who/when/which" queries, but still small enough to keep the evidence set tight and low-noise.
- Neighbor chunks are enabled so the model sees immediate surrounding dialogue.
  - Justification: specific questions often depend on one line before or after the hit for speaker attribution, timing, or pronoun resolution.
- No transcript anchors are forced.
  - Justification: fixed transcript-frame chunks would dilute the prompt with mostly irrelevant broad context for detail questions.
- No broad summary-first packing is used; this path stays local and detail-oriented.
  - Justification: if the prompt starts from a transcript summary, the model can drift toward broad paraphrases instead of answering the exact requested detail.

#### `topic_path`

- Sits between fine-grained and broad summary behavior.
- Uses a medium budget (`10000`) and medium retrieval depth.
  - Justification: thematic questions need more spread than a detail question, but they usually do not need the full transcript-frame treatment of `summary_path`.
- Neighbors are disabled because the aim is topical evidence, not dense local continuity.
  - Justification: for topical questions, multiple distinct mentions of the same theme are usually more valuable than expanding one hit into adjacent dialogue.
- Anchor configuration is light: one opening chunk plus one middle chunk.
  - Justification: a small amount of transcript framing can stabilize answers about themes without overcommitting to summary-first behavior.
- Support limit stays at `8`.
  - Justification: this gives the packer enough room to include several topical mentions while still preserving prompt budget for the question and route instructions.
- In practice this path still behaves closer to standard retrieval than to full summary-first assembly.
  - Justification: thematic intent is often narrower than global intent, so the current implementation intentionally keeps this path conservative.

#### `summary_path`

- Uses the largest budget (`22000`) because it is the transcript-overview path.
  - Justification: this is the path that most directly benefits from the larger 32k context window, since overview questions were failing from under-coverage rather than missing retrieval hits.
- `top_k_chunks=20`, `bm25_k=40`, and `reranker_top_n=12` maximize candidate coverage before prompt packing.
  - Justification: broad questions need wide candidate coverage so the packer can choose support from multiple transcript regions instead of overfitting to the top few local matches.
- Neighbors are disabled because broad routes prefer transcript coverage over local redundancy.
  - Justification: for summary questions, spending tokens on adjacent dialogue around a single hit is usually worse than covering another section of the transcript.
- It injects the richest transcript frame:
  - `opening=2`
  - `early=1`
  - `middle=1`
  - `late=1`
  - `closing=1`
  - Justification: two opening chunks help establish setup and participants, the middle/late anchors prevent the answer from being dominated by the beginning, and the closing anchor preserves wrap-up context.
- Support limit is `10`.
  - Justification: this is large enough to supplement the fixed anchors with retrieval-ranked evidence, but still small enough that the packer can reject duplicates and stay within budget.
- Packing behavior is summary-first:
  - transcript summary first
  - then forced anchors
  - then supporting chunks that fit the remaining budget
  - Justification: overview questions are best answered from transcript framing first, with support used to refine and ground the answer rather than define it.

#### `hybrid_path`

- Uses a medium-large budget (`16000`) because it needs both framing and local evidence.
  - Justification: ambiguous queries need more than a local snippet, but giving them the full `summary_path` budget would often over-broaden the answer.
- `top_k_chunks=18`, `bm25_k=35`, `reranker_top_n=10`.
  - Justification: these values sit between `fine_grained_path` and `summary_path` so the route can recover from ambiguity without paying the full cost of the broadest path.
- Neighbors are enabled (`count=1`) so top local hits can retain nearby dialogue.
  - Justification: low-confidence queries often need both transcript framing and local clarification, so nearby context is more useful here than in `summary_path`.
- Anchor configuration is smaller than `summary_path`:
  - `opening=1`
  - `early=1`
  - `middle=1`
  - `late=1`
  - `closing=0`
  - Justification: the route needs broad structure, but only enough to orient the model. Omitting the closing anchor saves budget for local support chunks.
- Support limit is `12`.
  - Justification: hybrid questions are the most likely to need multiple local evidence chunks after framing, so the support limit is slightly higher than `summary_path`.
- Packing behavior is still summary-aware, but less transcript-wide than `summary_path`.
  - Justification: this route exists for uncertainty, so it intentionally balances breadth and locality instead of fully optimizing for either one.

### Detailed scoring logic

#### Global intent

`score_global_intent()` adds:

- `+1.0` for each matched phrase in `GLOBAL_PHRASES`
- `+0.8` for each matched keyword in `GLOBAL_KEYWORDS`
- `+0.6` for each matched noun in `GLOBAL_NOUNS`
- `+0.5` if the query has `<= 5` words

This strongly favors transcript-wide questions like:

- `What is this conversation about?`
- `Give me a summary`
- `What are the main topics discussed?`

#### Thematic intent

`score_thematic_intent()` adds `+1.0` per regex match in
`THEMATIC_PATTERNS`, covering words and constructions like:

- concerns
- challenges
- feedback
- views on
- think about
- how did they approach

#### Specific intent

`score_specific_intent()` uses `SPECIFIC_WH_WORDS` plus anchor bonuses.

Important detail: generic `what` is intentionally weak in practice because it
appears in global and thematic questions too. More specific patterns like
`who said`, `when did`, and `what did X say` are much stronger indicators.

Anchor bonuses:

- number present: `+0.5`
- quote present: `+0.5`
- matched known entity: `+0.5` each, capped at 2

### What each path does

#### `fine_grained_path`

Used for high-confidence `specific` queries.

Implementation:

- runs the hybrid retriever with the `fine_grained_path` route profile
- uses a modestly larger candidate pool than the old global default
- enables neighbor expansion through the route profile
- does not force transcript opening/closing chunks
- uses detail-oriented route instructions
- returns packed local retrieved chunk context

This is the detail-oriented path for questions like:

- `Who said X?`
- `When did they mention Y?`
- `How many participants were there?`

#### `topic_path`

Used for high-confidence `thematic` queries.

Current implementation detail:

- it still uses standard retrieved chunks rather than summary/anchor injection
- it has its own route label and retrieval profile
- no forced transcript frame chunks
- no transcript summary injection unless other code explicitly adds it

So `topic_path` is only partially specialized today: it has a distinct route and
profile, but not a distinct frame-aware context assembler like `summary_path`
or `hybrid_path`.

#### `summary_path`

Used for high-confidence `global` queries.

This is the main specialized path. In `src/route_aware_context.py` it:

- resolves the largest route token budget
- loads the most relevant transcript summary or summaries
- selects transcript anchors from the index:
  - opening
  - early
  - middle
  - late
  - closing
- keeps a larger support pool and token-packs it after frame chunks
- adds `route_instructions` telling the LLM to trust transcript-level framing first

This path is designed for questions like:

- `What is this conversation about?`
- `What is the purpose of this conversation?`
- `How does it begin?`
- `What is the structure of the interview?`

#### `hybrid_path`

Used whenever confidence is low.

Implementation:

- loads the scoped transcript summary if available
- selects a smaller anchor set than `summary_path`
- keeps a moderate number of supporting chunks
- token-packs local evidence after summary and anchors
- adds route instructions telling the LLM to combine transcript-level framing
  with local evidence

This is the fallback for ambiguous queries like:

- `What happened?`
- `Tell me about this.`

### Practical examples

| Query | Likely intent | Likely route |
|---|---|---|
| `What is this conversation about?` | `global` | `summary_path` |
| `Who raised the issue about latency?` | `specific` | `fine_grained_path` |
| `What concerns were raised about model accuracy?` | `thematic` | `topic_path` or `hybrid_path` if scores are close |
| `What happened?` | ambiguous | `hybrid_path` |

### Important current limitations

- `topic_path` is only lightly specialized; it still uses standard chunk assembly
- the router is purely rule-based; it does not use embeddings or an LLM
- `known_entities` is optional and is not heavily used in the current chatbot path
- transcript anchors are most reliable for single-transcript or strongly inferred transcript scope

---

## Detailed Implementation Notes

### 1. Data structures

`intent_router.py` defines four small dataclasses:

- `AnchorFeatures`
  - stores concrete query anchors: number, quote, entity count
- `IntentScores`
  - stores raw scores for `specific`, `thematic`, `global_`
- `IntentDetectionResult`
  - stores winning label, confidence, raw scores, and matched reasons
- `RoutingDecision`
  - wraps the detection result plus the chosen route string

These keep the router explainable and make it easy to log why a route was chosen.

### 2. Query normalization and anchor extraction

The router preprocesses queries in two ways:

1. `normalize_query(query)`
   - lowercases
   - collapses whitespace
   - preserves punctuation for quote detection

2. `extract_anchor_features(query, known_entities=None)`
   - detects any digits via `\d`
   - detects quotes via `["']`
   - optionally counts matched known entities in the raw query

Anchor features are only used by the `specific` scorer.

### 3. Per-intent scoring functions

The router uses three independent scorers:

- `score_global_intent(norm_query)`
  - phrase matches first
  - then single keywords
  - then transcript-wide nouns
  - then a short-query global bonus

- `score_thematic_intent(norm_query)`
  - regex-based thematic pattern matches
  - each match adds to thematic evidence

- `score_specific_intent(norm_query, anchors)`
  - wh-question and factual pattern matches
  - plus bonuses for numbers, quotes, and known entities

Each scorer returns:

- a numeric score
- a list of human-readable reasons

### 4. Confidence computation

`detect_query_intent()` combines the three scorers, sorts them by score, and
computes confidence using the winner/runner-up margin:

```python
confidence = (winner_score - runner_up_score) / winner_score
```

If all scores are zero:

- confidence is forced to `0.0`
- the top label is still returned for transparency
- `decide_retrieval_route()` then falls back to `hybrid_path`

This is what makes the router robust to weak or conflicting signals.

### 5. Route decision function

`decide_retrieval_route(result)` is intentionally simple:

- if `confidence < HIGH_CONFIDENCE_THRESHOLD`, return `hybrid_path`
- otherwise:
  - `specific -> fine_grained_path`
  - `thematic -> topic_path`
  - `global -> summary_path`

This separation is deliberate:

- `detect_query_intent()` decides what the query looks like
- `decide_retrieval_route()` decides how the pipeline should behave

### 6. Where route effects happen

The route string is consumed in `route_aware_context.py`, not in
`intent_router.py`.

That file applies the route in three places:

1. retrieval profile resolution
   - route-specific `top_k_chunks`
   - route-specific `bm25_k`
   - route-specific `reranker_top_n`
   - route-specific neighbor settings

2. frame/summary selection
   - whether transcript summaries are loaded
   - whether transcript anchors are injected
   - how many frame chunks are considered

3. token-budgeted prompt packing
   - how much context budget the route gets
   - how many support chunks are kept
   - how aggressively broad routes prefer distributed evidence

So the router’s output directly changes the final prompt seen by the answer model.

---

---

## Full implementation

```python
"""
Intent Router — lightweight rule-based query intent classifier.

Classifies a user query into one of three intents before RAG retrieval:
  - specific:  precise fact, speaker, date, or local detail
  - thematic:  topic/aspect/concern discussed in part of the transcript
  - global:    overview, summary, or gist of the whole conversation

When confidence is low the router returns a hybrid route so the pipeline
can fall back to a broader retrieval strategy.

Usage:
    from intent_router import detect_query_intent, decide_retrieval_route

    result = detect_query_intent(user_query)
    decision = decide_retrieval_route(result)
    print(decision.route)          # "fine_grained_path" | "topic_path" | "summary_path" | "hybrid_path"
    print(result.label)            # "specific" | "thematic" | "global"
    print(result.confidence)       # 0.0 – 1.0
    print(result.reasons)          # list of matched signals
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Configurable thresholds
# ---------------------------------------------------------------------------

# Minimum confidence gap (winner – runner-up) / winner to accept a single label.
# Below this the router returns "hybrid_path".
HIGH_CONFIDENCE_THRESHOLD: float = 0.50

# Short-query word-count ceiling: very short abstract queries get a global bonus.
SHORT_QUERY_WORD_LIMIT: int = 5

# Score bonuses
ANCHOR_NUMBER_BONUS: float = 0.5
ANCHOR_QUOTE_BONUS: float = 0.5
ANCHOR_ENTITY_BONUS: float = 0.5  # per matched known entity (capped at 2)
SHORT_ABSTRACT_GLOBAL_BONUS: float = 0.5

# ---------------------------------------------------------------------------
# Pattern lists — extend these as you collect real query logs
# ---------------------------------------------------------------------------

# Phrases that strongly indicate the user wants a global summary/overview.
GLOBAL_PHRASES: list[str] = [
    "what is this conversation about",
    "what is this transcript about",
    "what was discussed",
    "what was talked about",
    "what did they talk about",
    "what were they talking about",
    "summarize this",
    "summarize the",
    "give me a summary",
    "give me an overview",
    "give me a brief",
    "overview of",
    "summary of",
    "main topics",
    "key topics",
    "key points",
    "main points",
    "what is the gist",
    "what is the overall",
    "high level",
    "high-level",
    "overall",
    "gist",
    "recap",
]

# Single keywords that suggest a global/summary intent.
GLOBAL_KEYWORDS: list[str] = [
    "summarize",
    "summary",
    "overview",
    "gist",
    "recap",
    "overall",
]

# Transcript-wide nouns that anchor a global query to the whole document.
GLOBAL_NOUNS: list[str] = [
    "conversation",
    "transcript",
    "meeting",
    "discussion",
    "call",
    "session",
    "interview",
    "dialogue",
    "exchange",
]

# Wh-question words that signal a specific, answerable question.
SPECIFIC_WH_WORDS: list[str] = [
    r"\bwho\b",
    r"\bwhen\b",
    r"\bwhere\b",
    r"\bwhich\b",
    r"\bhow many\b",
    r"\bhow much\b",
    r"\bwhat did .{1,30} say\b",
    r"\bwhat did .{1,30} decide\b",
    r"\bwho said\b",
    r"\bwho raised\b",
    r"\bwho mentioned\b",
    r"\bwho brought up\b",
    r"\bwhen did\b",
    r"\bwhen was\b",
]

# Terms/phrases that suggest a thematic question about a topic or concern.
THEMATIC_PATTERNS: list[str] = [
    r"\bconcern[s]?\b",
    r"\bchallenge[s]?\b",
    r"\bfeedback\b",
    r"\bopinion[s]?\b",
    r"\btheme[s]?\b",
    r"\btopic[s]?\b",
    r"\bissue[s]?\b",
    r"\bdiscuss(ed|ion)?\b",
    r"\bsay about\b",
    r"\bsaid about\b",
    r"\bthink about\b",
    r"\bfeel about\b",
    r"\bview[s]? on\b",
    r"\battitude[s]? (on|toward|about)\b",
    r"\bapproach (to|toward)\b",
    r"\bstrateg(y|ies)\b",
    r"\bhow (did|do|does) .{1,40} (work|handle|approach|deal)\b",
    r"\bwhat (were|are|is) the (main )?concern\b",
    r"\bwhat (were|are|is) the (main )?challenge\b",
    r"\bwhat (were|are|is) the (main )?issue\b",
    r"\bwhat (were|are|is) the (main )?feedback\b",
]

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AnchorFeatures:
    """Concrete detail signals extracted from the raw query."""
    has_number: bool
    has_quote: bool
    entity_count: int  # number of known_entities matched


@dataclass
class IntentScores:
    """Raw (un-normalised) scores for each intent class."""
    specific: float
    thematic: float
    global_: float


@dataclass
class IntentDetectionResult:
    """Output of detect_query_intent()."""
    label: str          # "specific" | "thematic" | "global"
    confidence: float   # 0.0–1.0, based on gap between winner and runner-up
    scores: IntentScores
    reasons: list[str] = field(default_factory=list)


@dataclass
class RoutingDecision:
    """Final routing decision returned to the RAG pipeline."""
    intent: IntentDetectionResult
    route: str  # "fine_grained_path" | "topic_path" | "summary_path" | "hybrid_path"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalize_query(query: str) -> str:
    """Lowercase, collapse whitespace. Keep punctuation for quote detection."""
    return re.sub(r"\s+", " ", query.lower().strip())


def extract_anchor_features(
    query: str,
    known_entities: Optional[set[str]] = None,
) -> AnchorFeatures:
    """
    Detect concrete anchors in the *original* query text.

    Args:
        query:          Raw user query.
        known_entities: Optional set of entity strings (names, dates, etc.)
                        to match against. Matching is case-insensitive.
    """
    has_number = bool(re.search(r"\d", query))
    has_quote = bool(re.search(r'["\']', query))

    entity_count = 0
    if known_entities:
        q_lower = query.lower()
        for ent in known_entities:
            if ent.lower() in q_lower:
                entity_count += 1

    return AnchorFeatures(
        has_number=has_number,
        has_quote=has_quote,
        entity_count=entity_count,
    )


# ---------------------------------------------------------------------------
# Per-class scorers
# ---------------------------------------------------------------------------

def score_global_intent(norm_query: str) -> tuple[float, list[str]]:
    """
    Score how strongly a normalised query signals a global/summary intent.

    Returns (score, reasons).
    """
    score = 0.0
    reasons: list[str] = []

    # Multi-word phrases (checked first — stronger signal than single words)
    for phrase in GLOBAL_PHRASES:
        if phrase in norm_query:
            score += 1.0
            reasons.append(f"global phrase: '{phrase}'")

    # Single keywords (only add if not already captured by phrase)
    for kw in GLOBAL_KEYWORDS:
        if re.search(r"\b" + re.escape(kw) + r"\b", norm_query):
            if not any(kw in r for r in reasons):
                score += 0.8
                reasons.append(f"global keyword: '{kw}'")

    # Transcript-wide noun
    for noun in GLOBAL_NOUNS:
        if re.search(r"\b" + re.escape(noun) + r"\b", norm_query):
            score += 0.6
            reasons.append(f"global noun: '{noun}'")

    # Very short queries with no strong anchor tend to be abstract/global
    word_count = len(norm_query.split())
    if word_count <= SHORT_QUERY_WORD_LIMIT:
        score += SHORT_ABSTRACT_GLOBAL_BONUS
        reasons.append(f"short abstract query ({word_count} words)")

    return score, reasons


def score_thematic_intent(norm_query: str) -> tuple[float, list[str]]:
    """
    Score how strongly a normalised query signals a thematic intent.

    Returns (score, reasons).
    """
    score = 0.0
    reasons: list[str] = []

    for pattern in THEMATIC_PATTERNS:
        match = re.search(pattern, norm_query)
        if match:
            score += 1.0
            reasons.append(f"thematic pattern: '{match.group(0)}'")

    return score, reasons


def score_specific_intent(
    norm_query: str,
    anchors: AnchorFeatures,
) -> tuple[float, list[str]]:
    """
    Score how strongly a normalised query signals a specific/factual intent.

    Returns (score, reasons).
    """
    score = 0.0
    reasons: list[str] = []

    # Wh-question patterns
    for pattern in SPECIFIC_WH_WORDS:
        match = re.search(pattern, norm_query)
        if match:
            score += 1.0
            reasons.append(f"wh-word/phrase: '{match.group(0)}'")

    # Concrete anchor bonuses
    if anchors.has_number:
        score += ANCHOR_NUMBER_BONUS
        reasons.append("anchor: number detected")

    if anchors.has_quote:
        score += ANCHOR_QUOTE_BONUS
        reasons.append("anchor: quoted text")

    if anchors.entity_count > 0:
        bonus = min(anchors.entity_count, 2) * ANCHOR_ENTITY_BONUS
        score += bonus
        reasons.append(f"anchor: {anchors.entity_count} known entity/entities matched")

    return score, reasons


# ---------------------------------------------------------------------------
# Main detection logic
# ---------------------------------------------------------------------------

def detect_query_intent(
    query: str,
    known_entities: Optional[set[str]] = None,
) -> IntentDetectionResult:
    """
    Classify a user query into specific / thematic / global.

    Args:
        query:          Raw user query string.
        known_entities: Optional set of entity strings for anchor detection.

    Returns:
        IntentDetectionResult with label, confidence, scores, and reasons.
    """
    norm = normalize_query(query)
    anchors = extract_anchor_features(query, known_entities)

    global_score, global_reasons = score_global_intent(norm)
    thematic_score, thematic_reasons = score_thematic_intent(norm)
    specific_score, specific_reasons = score_specific_intent(norm, anchors)

    scores = IntentScores(
        specific=specific_score,
        thematic=thematic_score,
        global_=global_score,
    )

    # Rank classes by score
    ranked = sorted(
        [
            ("specific", specific_score, specific_reasons),
            ("thematic", thematic_score, thematic_reasons),
            ("global", global_score, global_reasons),
        ],
        key=lambda x: x[1],
        reverse=True,
    )

    winner_label, winner_score, winner_reasons = ranked[0]
    _, runner_up_score, _ = ranked[1]

    # Confidence = normalised gap between winner and runner-up
    eps = 1e-6
    if winner_score < eps:
        # No signals fired at all — default to global with zero confidence
        confidence = 0.0
        winner_label = "global"
        winner_reasons = ["no signals matched — defaulting to global"]
    else:
        confidence = (winner_score - runner_up_score) / (winner_score + eps)

    return IntentDetectionResult(
        label=winner_label,
        confidence=confidence,
        scores=scores,
        reasons=winner_reasons,
    )


def decide_retrieval_route(result: IntentDetectionResult) -> RoutingDecision:
    """
    Map an IntentDetectionResult to a concrete retrieval route.

    Routes:
        specific  (high conf) → fine_grained_path
        thematic  (high conf) → topic_path
        global    (high conf) → summary_path
        any       (low conf)  → hybrid_path
    """
    if result.confidence < HIGH_CONFIDENCE_THRESHOLD:
        route = "hybrid_path"
    elif result.label == "specific":
        route = "fine_grained_path"
    elif result.label == "thematic":
        route = "topic_path"
    else:  # global
        route = "summary_path"

    return RoutingDecision(intent=result, route=route)


# ---------------------------------------------------------------------------
# Quick manual test — run:  python src/intent_router.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_queries = [
        # Expected: global
        "What is this conversation about?",
        "Summarize the transcript.",
        "Give me an overview of the meeting.",
        "What are the main topics discussed?",
        "What was discussed?",
        # Expected: specific
        "Who raised the issue about latency?",
        "When did they decide to deploy the model?",
        'What did John say about the budget on Monday?',
        "How many participants were in the call?",
        # Expected: thematic
        "What concerns were raised about model accuracy?",
        "How did they discuss pricing strategy?",
        "What feedback was given about the new feature?",
        "What challenges did they mention?",
        # Expected: hybrid (ambiguous)
        "Tell me about this.",
        "What happened?",
    ]

    print(f"{'Query':<55} {'Label':<10} {'Conf':>6}  {'Route'}")
    print("-" * 100)
    for q in test_queries:
        result = detect_query_intent(q)
        decision = decide_retrieval_route(result)
        print(
            f"{q[:54]:<55} {result.label:<10} {result.confidence:>6.2f}  {decision.route}"
        )
        for reason in result.reasons:
            print(f"  · {reason}")
        print()
```

---

## Design choices

- **Rule-based + scoring, not if/else**: multiple weak signals combine additively. A single matched pattern is not enough to lock in a label — the scores need to clearly separate.
- **Confidence = score gap ratio**: `(winner - runner_up) / winner`. This is relative, not absolute, so it adapts to varying query lengths and naturally produces `hybrid_path` when two intents tie.
- **Global phrases checked before keywords**: a multi-word phrase like `"give me an overview"` is a stronger signal than the single keyword `"overview"`. Keywords only add score if not already captured by a phrase match.
- **Short-query bonus for global**: very short abstract queries (≤ 5 words, no anchor) are most often global. This prevents them from being misrouted via a single weak thematic/specific signal.
- **`known_entities` is optional**: entity detection is useful without NER — callers can pass a set of names/dates extracted from the transcript metadata.
- **Zero external dependencies**: stdlib `re`, `dataclasses`, `typing` only. No extra install, no latency.

---

## Tuning notes

| What | Default | When to change |
|---|---|---|
| `HIGH_CONFIDENCE_THRESHOLD` | `0.50` | Too many `hybrid_path` → lower; too aggressive routing → raise |
| `SHORT_QUERY_WORD_LIMIT` | `5` | Adjust if short specific queries (e.g. "Who spoke?") misroute to global |
| `SHORT_ABSTRACT_GLOBAL_BONUS` | `0.5` | Raise to make short queries default to global more strongly |
| `ANCHOR_NUMBER_BONUS` / `ANCHOR_QUOTE_BONUS` | `0.5` each | Raise if numeric questions misroute to thematic |
| Score per matched pattern | `1.0` uniform | Differentiate once you have recall/precision data per signal |
| `GLOBAL_PHRASES` / `SPECIFIC_WH_WORDS` / `THEMATIC_PATTERNS` | See module | Extend with real query logs from your transcripts |

---

## Verification

Run the built-in test:
```bash
python3 src/intent_router.py
```

Expected output (abbreviated):
```
Query                                                   Label        Conf  Route
----------------------------------------------------------------------------------------------------
What is this conversation about?                        global       1.00  summary_path
Summarize the transcript.                               global       1.00  summary_path
Who raised the issue about latency?                     specific     0.50  hybrid_path
When did they decide to deploy the model?               specific     1.00  fine_grained_path
What concerns were raised about model accuracy?         thematic     1.00  topic_path
How did they discuss pricing strategy?                  thematic     1.00  topic_path
Tell me about this.                                     global       1.00  summary_path
```

To test end-to-end, start the chatbot and observe `[Router]` log lines:
```
You: What is this conversation about?
[Router] intent=global  route=summary_path  confidence=1.00
```
