# RAG Implementation

## Overview

The RAG pipeline answers questions over transcripts by retrieving the most relevant chunks from a global multi-transcript vector store, augmenting them with a pre-built transcript summary when available, and sending everything to an LLM. It now uses route-specific retrieval profiles and token-budgeted prompt assembly so vague questions get transcript-level framing plus wider evidence coverage instead of only local chunk matches. The key design goals are:

- **Accuracy on specific questions**: hybrid retrieval (vector + BM25 + phonetic + fuzzy) with RRF fusion and cross-encoder reranking
- **Accuracy on vague/overview questions**: route-aware context assembly with transcript summaries, transcript anchors, and larger packed evidence sets
- **Scale**: a single global Chroma index stores all transcripts; queries can be scoped or global

---

## Pipeline Architecture

```
User Query
    │
    ▼
Intent Router                    intent_router.py
    │  (specific / thematic / global)
    │
    ▼
Route Selection + Retrieval
Profile Resolution              route_aware_context.py + rag_config.py
    ├── fine_grained_path
    ├── topic_path
    ├── summary_path
    └── hybrid_path
    │  (applies route-specific top-k, rerank depth, neighbors, frame limits, budgets)
    │
    ▼
Parallel Retrieval                retrieval_core.py
    ├── Vector Search             Chroma + Qwen embeddings (localhost:8081)
    ├── BM25 Search               bm25_retriever.py
    ├── Phonetic Search           phonetic_indexer.py  (Double Metaphone)
    └── Fuzzy Search              fuzzy_matcher.py     (RapidFuzz)
    │
    ▼
RRF Fusion                        fusion.py
    │  (Reciprocal Rank Fusion — combines all signals with configurable weights)
    │
    ▼
[Optional] Neighbor Chunk Expansion
    │  (expands each hit to include N adjacent chunks for more context)
    │
    ▼
[Optional] Cross-Encoder Reranker reranker.py   (localhost:8082)
    │  (re-scores fused candidates, keeps top-N)
    │
    ▼
Route-Aware Context Assembly      route_aware_context.py
    ├── summary_path: summary + opening/early/middle/late/closing anchors + packed support
    ├── hybrid_path: summary + anchors + packed local support
    ├── fine_grained_path: detail-oriented packed local context
    └── topic_path: topic-focused retrieved chunks
    │
    ▼
Prompt Assembly                   prompt_templates.py
    ├── Route instructions
    ├── Transcript Summary block  summaries/<transcript_id>.json  (if scoped)
    └── Retrieved / forced transcript excerpts
    │
    ▼
LLM                               local Qwen (localhost:8080) or DeepSeek API
    │
    ▼
Response
```

---

## File Structure

```
/Users/tohkarle/Desktop/Coding/Python/LangChain/
├── src/
│   ├── chatbot.py               Main CLI chatbot app
│   ├── rag_config.py            All configuration constants
│   ├── rag_initializer.py       Vector store loading and retriever setup
│   ├── rag_retriever.py         High-level retrieval interface (retrieve_for_chatbot)
│   ├── retrieval_core.py        Core retrieval logic: vector, BM25, phonetic, fuzzy
│   ├── route_aware_context.py   Shared route-aware context assembly for chatbot + vague eval
│   ├── fusion.py                Reciprocal Rank Fusion implementation
│   ├── bm25_retriever.py        BM25 keyword search
│   ├── phonetic_indexer.py      Double Metaphone phonetic search
│   ├── fuzzy_matcher.py         RapidFuzz edit-distance matching
│   ├── reranker.py              Cross-encoder reranker
│   ├── prompt_templates.py      All prompt templates + summary formatting helpers
│   ├── summarize_transcript.py  Pipeline to generate summary JSON files
│   ├── intent_router.py         Query intent classification (specific/thematic/global)
│   ├── srt_parser.py            SRT file parser (chunks with timestamps + speaker)
│   ├── document_processor.py    Converts SRT chunks to LangChain Documents
│   ├── token_utils.py           Token counting utilities
│   └── ...
├── summaries/                   Pre-built transcript summaries (JSON)
│   ├── example_transcript_1.json
│   └── ...
├── transcripts/                 Source SRT transcript files
├── vector_stores/
│   └── global_combined/         Global Chroma vector store + BM25/phonetic indices
└── RAG_IMPLEMENTATION.md        This file
```

---

## Key Components

### 1. Global Index

All transcripts are embedded and stored together in a single Chroma collection at `vector_stores/global_combined/`. Each chunk's metadata includes `transcript_id` (derived from the SRT filename) so queries can be filtered to specific transcripts.

- **Build**: `python build_global_index.py`
- **Load**: `rag_initializer.py → RAGInitializer.load_global_vector_store()`
- Chunk metadata: `transcript_id`, `source`, `chunk_id`, `start_time`, `end_time`, `sequence`

### 2. Hybrid Retrieval (`retrieval_core.py`)

Four signals run in parallel per query:

| Signal | Method | Default top-k |
|--------|--------|---------------|
| Vector | Chroma cosine similarity (Qwen embeddings) | 10 |
| BM25 | Term-frequency keyword matching | 25 |
| Phonetic | Double Metaphone sound-alike matching | 10 |
| Fuzzy | RapidFuzz edit-distance on rare tokens | 10 |

Phonetic and fuzzy are especially useful for ASR transcripts where words are frequently misspelled or misheard.

### 3. RRF Fusion (`fusion.py`)

Reciprocal Rank Fusion combines the ranked lists from all signals:

```
score(chunk) = Σ  weight_i / (k + rank_i(chunk))
```

where `k = 60` (standard RRF constant). Weights are configurable:
- Vector: `VECTOR_WEIGHT = 1`
- BM25: `BM25_WEIGHT = 1`
- Phonetic: `PHONETIC_WEIGHT = 0.2`
- Fuzzy: `FUZZY_WEIGHT = 0.2`

### 4. Neighbor Chunk Expansion

When `NEIGHBOR_CHUNKS_ENABLED = True`, each retrieved chunk is expanded to include `NEIGHBOR_CHUNKS_COUNT` adjacent chunks before and after it in the transcript. This adds conversational context around each hit.

Global default: disabled (`NEIGHBOR_CHUNKS_ENABLED = False`). Route-aware retrieval can override this per route through `ROUTE_RETRIEVAL_PROFILES`, so `fine_grained_path` can stay detail-oriented while still seeing local surrounding dialogue.

### 5. Cross-Encoder Reranker (`reranker.py`)

A cross-encoder model (running at `localhost:8082`) jointly encodes the query and each candidate chunk to produce a relevance score more accurate than embedding similarity alone. After fusion, all candidates are re-scored and collapsed to `RERANKER_TOP_N = 5`.

Default: enabled (`RERANKER_ENABLED = True`).

### 6. Route-Aware Summary + Chunks Prompt

Pre-built transcript summaries improve accuracy on vague overview questions ("What is this about?", "What topics are covered?") that chunk retrieval alone handles poorly. The current implementation goes beyond raw summary injection and assembles prompt context differently depending on query intent.

**How it works:**
1. `intent_router.py` classifies the query as `specific`, `thematic`, or `global`
2. `route_aware_context.py` maps that to a retrieval route
3. `rag_config.py` provides route-scoped overrides through:
   - `ROUTE_CONTEXT_TOKEN_BUDGETS`
   - `ROUTE_RETRIEVAL_PROFILES`
   - `ROUTE_SUPPORTING_LIMITS`
   - `ROUTE_FRAME_LIMITS`
4. Retrieval runs with the selected route profile, which can override semantic `top_k`, BM25 pool size, rerank depth, and neighbor expansion
5. The assembler loads summaries for the most relevant transcript(s)
6. For broad routes, the assembler selects transcript anchors chronologically from the index:
   - opening
   - early
   - middle
   - late
   - closing
7. Prompt context is token-packed in priority order:
   - route instructions
   - transcript summary
   - forced frame chunks
   - supporting documents
8. Supporting documents are deduplicated and near-duplicate text is suppressed
9. Broad routes sort packed evidence chronologically after selection

**When no summary is injected:**
- If no relevant scoped or inferred transcript summary exists, the summary block is omitted
- If a summary file is missing, the route-aware path gracefully falls back to retrieved chunks only

**Current route defaults:**
- `fine_grained_path`: modestly larger candidate pool, reranked to a medium final set, neighbor expansion enabled
- `topic_path`: standard topic-focused retrieval with a medium token budget
- `summary_path`: largest context budget, summary-first framing, distributed anchors, broader support set
- `hybrid_path`: summary + anchors + local evidence, with a medium-large packed support set

**Summary plain-text format:**
```
Transcript Summary:
Participants: <participant names or roles>
Conversation Type: <interview|podcast|meeting|...>
Purpose: <purpose>
Opening Context: <how the conversation begins>
Structure: <how the conversation is organized>
Closing Context: <how the conversation ends>

Overview: <overview sentence>

Key Topics: topic1, topic2, topic3

Main Topics Detailed:
  - <Topic>: <why it matters in this transcript>

Recurring Themes: theme1, theme2

Outline:
  1. <Section Title>: <1-2 sentence summary>
  2. ...

Notable Segments:
  - <Segment Title>: <notable moment description>

Action Items:
  - [Owner] Task description (due: deadline)

Entities: Name1 (type), Name2 (type)

Relevant excerpts from the transcript:
<forced transcript frame excerpts + retrieved supporting chunks>
```

### 7. Transcript Filtering

`--transcripts` scopes all retrieval to specific transcript IDs. Internally, the transcript filename is converted to an ID (`.srt` stripped, `.` replaced with `_`) and used as a Chroma metadata filter.

### 8. Intent Router (`intent_router.py`)

Classifies queries as `specific`, `thematic`, or `global` and routes them to different context assembly strategies.

- `fine_grained_path`: standard retrieved chunks
- `topic_path`: standard retrieved chunks
- `summary_path`: summary-first prompt with opening/early/middle/late/closing transcript anchors plus packed support
- `hybrid_path`: summary + anchors + supporting retrieved chunks

This router is now active in the chatbot and reused by `evaluate_vague_speed.py` via `route_aware_context.py`.

---

## Summary Files

**Location:** `summaries/<transcript_id>.json`

**Schema:**
```json
{
  "transcript_id": "example_transcript_1",
  "source": "transcripts/example_transcript_1.srt",
  "participants": ["participant", "interviewer"],
  "conversation_type": "interview",
  "purpose": "Main purpose of the conversation",
  "opening_context": "How the conversation begins",
  "closing_context": "How the conversation ends",
  "structure": "High-level transcript structure",
  "overview": "High-level summary of entire transcript",
  "key_topics": ["topic1", "topic2"],
  "main_topics_detailed": [
    {"title": "Topic title", "summary": "Why this topic matters in the transcript"}
  ],
  "participants_with_roles": [
    {"name": "Marquez", "role": "host"}
  ],
  "recurring_themes": ["theme1", "theme2"],
  "outline": [
    {"title": "Section Title", "summary": "1-2 sentence summary"}
  ],
  "notable_segments": [
    {"title": "Memorable segment", "summary": "What happened in that segment"}
  ],
  "action_items": [
    {"owner": "Name or null", "task": "Task description", "deadline": "Deadline or null"}
  ],
  "entities": [
    {"name": "Entity name", "type": "person|company|product|technology|unknown"}
  ],
  "_timing": {"total_seconds": 26.05, "num_chunks": 1}
}
```

**Generation:** `python summarize_transcript.py` — runs a two-stage LLM pipeline that extracts structured data per chunk, then merges all chunks into a single coherent summary with transcript-frame metadata.

**Formatting helpers** (in `prompt_templates.py`):
- `format_summary_as_text(summary: dict) -> str` — converts one summary JSON to plain text, omitting empty sections
- `format_summaries_as_text(summaries: list) -> str` — handles multiple transcripts, adds `--- Transcript: <id> ---` headers between them

---

## Prompt Design

**RAG system message** (`prompt_templates.py → RAG_SYSTEM_MESSAGE`):

```
You are a helpful assistant answering questions about a transcript.

{route_instructions}{transcript_summary}Relevant excerpts from the transcript:

{retrieved_context}

Use the summary and excerpts to answer the user's questions. If the answer cannot be found in the provided context, say so clearly. Do not make up information not present in the context.
```

- `{route_instructions}`: extra guidance for `summary_path` / `hybrid_path` telling the model to answer from transcript-level framing first
- `{transcript_summary}`: formatted summary block ending with `\n\n`, or empty string (global mode)
- `{retrieved_context}`: token-budgeted string of retrieved chunks or route-aware forced frame excerpts + supporting chunks

The chain also receives `{chat_history}` (multi-turn conversation) and `{question}`.

---

## Configuration (`rag_config.py`)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `ANSWER_MODEL` | `"local"` | `"local"` (Qwen at localhost:8080) or `"deepseek"` |
| `TOP_K_CHUNKS` | `10` | Vector search top-k (before reranking) |
| `SEARCH_TYPE` | `"similarity"` | `"similarity"` or `"mmr"` |
| `BM25_ENABLED` | `True` | Enable BM25 hybrid retrieval |
| `BM25_TOP_K` | `25` | BM25 result count |
| `PHONETIC_ENABLED` | `True` | Enable phonetic search |
| `PHONETIC_TOP_K` | `10` | Phonetic result count |
| `FUZZY_ENABLED` | `True` | Enable fuzzy matching |
| `FUZZY_TOP_K` | `10` | Fuzzy result count |
| `FUZZY_THRESHOLD` | `0.8` | Minimum similarity score |
| `VECTOR_WEIGHT` | `1` | RRF weight for vector signal |
| `BM25_WEIGHT` | `1` | RRF weight for BM25 signal |
| `PHONETIC_WEIGHT` | `0.2` | RRF weight for phonetic signal |
| `FUZZY_WEIGHT` | `0.2` | RRF weight for fuzzy signal |
| `HYBRID_FUSION_K` | `60` | RRF constant |
| `RERANKER_ENABLED` | `True` | Enable cross-encoder reranker |
| `RERANKER_TOP_N` | `5` | Chunks to keep after reranking |
| `NEIGHBOR_CHUNKS_ENABLED` | `False` | Expand hits with adjacent chunks |
| `NEIGHBOR_CHUNKS_COUNT` | `1` | Neighbors before+after each hit |
| `ROUTE_CONTEXT_TOKEN_BUDGETS` | route-dependent | Per-route prompt packing budgets |
| `ROUTE_RETRIEVAL_PROFILES` | route-dependent | Per-route retrieval depth, rerank depth, and neighbor behavior |
| `ROUTE_SUPPORTING_LIMITS` | route-dependent | Max supporting chunks considered before token packing |
| `ROUTE_FRAME_LIMITS` | route-dependent | Anchor counts for opening/early/middle/late/closing transcript sections |
| `MERGE_SMALL_CHUNKS` | `True` | Merge short SRT chunks at index time |
| `MIN_CHUNK_SIZE` | `25` | Min tokens before merging |
| `TARGET_MERGED_SIZE` | `128` | Target merged chunk size (tokens) |

---

## Usage

**Build the global index** (run once, or after adding new transcripts):
```bash
python src/build_global_index.py
```

**Summarize a transcript** (run once per transcript, saves to `summaries/`):
```bash
python src/summarize_transcript.py
```

**Regenerate all summaries after schema or prompt changes**:
```bash
python src/summarize_transcript.py --all --force
```

**Run chatbot — global search** (all transcripts, no summary injected):
```bash
python src/chatbot.py
```

**Run chatbot — scoped to one transcript** (with summary):
```bash
python src/chatbot.py --transcripts example_transcript_1.srt
```

For vague transcript-wide questions, the chatbot now automatically switches to the route-aware summary path.

**Run route-aware evaluation ablations**:
```bash
python3 evaluation/evaluate_rag.py --all --ablation baseline
python3 evaluation/evaluate_rag.py --all --ablation larger_support
python3 evaluation/evaluate_rag.py --all --ablation frame_plus_support
python3 evaluation/evaluate_rag.py --all --ablation full
python3 evaluation/evaluate_rag.py --all --ablation full_with_neighbors
```

`evaluate_rag.py` now records route-level breakdowns plus prompt, summary, frame, and support counts for each evaluated question.

**Run chatbot — scoped to multiple transcripts**:
```bash
python src/chatbot.py --transcripts example_transcript_1.srt,example_transcript_2.srt
```

**List available transcripts in the index:**
```bash
python src/chatbot.py --list-transcripts
```

---

## Troubleshooting

**"Failed to connect to embedding service"**
- Ensure Qwen embedding model is running: `curl http://localhost:8081/v1/models`

**"Cannot connect to LLM server"**
- Local mode: ensure Qwen LLM is running at `localhost:8080`
- DeepSeek mode: check `DEEPSEEK_API_KEY` in `.env`

**"Transcript ID not found in index"**
- Re-run `build_global_index.py` after adding new transcripts
- Use `--list-transcripts` to see what's currently indexed

**Reranker unavailable**
- System degrades gracefully: falls back to top-N chunks from RRF fusion without reranking
