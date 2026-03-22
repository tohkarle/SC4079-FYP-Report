# Summarize Transcript Implementation

## Overview
Implemented a hierarchical multi-stage summarization pipeline for long transcripts using the local Qwen LLM. A single full-context LLM call is not viable for long transcripts, so the pipeline uses chunking → per-chunk extraction → global merge synthesis. The final summary schema is now richer because the local model context window increased to 32,768 tokens, allowing more transcript-level structure to survive into the merge stage.

## Problem Solved
- **Before**: No summarization capability; transcripts too long for a single LLM call
- **After**: Any-length transcript → structured JSON summary with transcript framing, key topics, detailed topics, participant roles, notable segments, recurring themes, and action items

## Pipeline Architecture

```
Raw Transcript
      │
      ▼
┌─────────────────────┐
│  Stage 1: Chunking  │  split_transcript()
│  2000–4000 tokens   │  Speaker boundary detection + overlap
└─────────────────────┘
      │
      ▼ (parallel, max 3 concurrent)
┌─────────────────────┐
│  Stage 2: Extract   │  extract_chunk_summary()  [async]
│  per-chunk JSON     │  with_structured_output → JSON fallback
└─────────────────────┘
      │
      ▼
┌─────────────────────┐
│  Stage 3: Merge     │  merge_chunk_summaries()
│  deduplicate +      │  Single or hierarchical synthesis call
│  synthesize         │  within 32k context budget
└─────────────────────┘
      │
      ▼
  Final Summary (JSON)
```

## File Structure

```
/Users/tohkarle/Desktop/Coding/Python/LangChain/
├── src/
│   ├── summarize_transcript.py     # NEW: Complete pipeline
│   ├── rag_config.py               # MODIFIED: Added get_local_llm()
│   ├── prompt_templates.py         # MODIFIED: Added chunk/merge prompts
│   ├── document_processor.py       # Reused: extract_last_n_tokens()
│   └── token_utils.py              # Reused: get_token_counter()
```

## Key Changes

### 1. New Factory Function (`rag_config.py`)

Added `get_local_llm()` — always returns the local Qwen model regardless of `ANSWER_MODEL` setting. `streaming=False` is required for structured output and JSON parsing.

```python
def get_local_llm(temperature: float = 0.0):
    return ChatOpenAI(
        model=LLM_MODEL_NAME,
        openai_api_base=LLM_BASE_URL,   # http://localhost:8080/v1
        openai_api_key="not-needed",
        streaming=False,                 # Required for JSON output
        temperature=temperature
    )
```

### 2. New Prompts (`prompt_templates.py`)

Added two prompt factories following the existing `ChatPromptTemplate.from_messages()` pattern, both with `/no_think` suffix (Qwen-specific):

- `get_chunk_extraction_prompt()` — strict JSON schema for `ChunkSummary` extraction
- `get_merge_synthesis_prompt()` — synthesis + deduplication instructions for `FinalSummary`

### 3. Summarization Pipeline (`summarize_transcript.py`)

#### Pydantic Models

```python
class ActionItem(BaseModel):
    owner: Optional[str]      # null if not mentioned
    task: str
    deadline: Optional[str]   # null if not mentioned

class ChunkSummary(BaseModel):
    chunk_id: str
    overview: str
    discussion_points: List[str]
    action_items: List[ActionItem]
    outline_label: str
    entities: List[Entity]

class FinalSummary(BaseModel):
    participants: List[str]
    conversation_type: str
    purpose: str
    opening_context: str
    closing_context: str
    structure: str
    overview: str
    key_topics: List[str]
    main_topics_detailed: List[TopicDetail]
    participants_with_roles: List[ParticipantRole]
    recurring_themes: List[str]
    outline: List[OutlineSection]
    notable_segments: List[TopicDetail]
    action_items: List[ActionItem]
    entities: List[Entity]
```

#### Stage 1: `split_transcript(transcript) -> List[str]`

- Normalizes whitespace (collapses 3+ blank lines, strips trailing spaces)
- Detects speaker boundaries via regex: `^(?:[A-Z][A-Za-z\s]{1,30}:|>>? ?|\[[A-Za-z][A-Za-z\s]*\])`
- Accumulates lines into token-counted buffers
- Seals a chunk when:
  - Speaker boundary detected **and** buffer ≥ 2000 tokens, or
  - Adding the next line would exceed 4000 tokens (hard cap)
- Applies 100-token overlap using `extract_last_n_tokens()` from `document_processor.py`

#### Stage 2: `extract_chunk_summary(chunk, chunk_id) -> dict` (async)

Two-tier structured output with graceful fallback:

1. **Primary**: `llm.with_structured_output(ChunkSummary, method='json_schema')` — enforced at protocol level
2. **Fallback**: JSON prompt + `<think>` tag stripping + `JsonOutputParser` (used if server rejects JSON schema mode)

A module-level `_use_structured_output` flag permanently switches all subsequent calls to the fallback after the first failure — avoids repeated overhead.

Chunks are extracted in parallel via `asyncio.gather()` with `asyncio.Semaphore(3)` to cap concurrent LLM calls.

#### Stage 3: `merge_chunk_summaries(summaries) -> dict`

- Filters errored chunks (chunks with `_error` field)
- **Compresses** summaries via `_compress_for_merge()` — now keeps a compact subset of `discussion_points` while still dropping chunk-level entities (deduplicated separately in Python)
- Checks if the compressed payload fits within `_MERGE_PAYLOAD_BUDGET` (model context − prompt overhead)
- If it fits: single LLM synthesis call
- If it doesn't fit: **hierarchical merge** — batches of `_MERGE_BATCH_SIZE` (8) summaries are merged into intermediate `FinalSummary` dicts, which are then merged again in subsequent passes until everything fits in one final call
- Same structured output → fallback pattern as Stage 2
- LLM handles deduplication, normalization, and chronological ordering via prompt

#### Entry Point: `summarize_transcript(transcript) -> dict` (async)

```python
async def summarize_transcript(transcript: str) -> dict:
    chunks = split_transcript(transcript)           # Stage 1
    summaries = await _extract_all_chunks(chunks)   # Stage 2
    return merge_chunk_summaries(summaries)         # Stage 3
```

## Output Schema

```json
{
  "participants": ["Host", "Guest"],
  "conversation_type": "podcast",
  "purpose": "Discuss current tech news and product updates",
  "opening_context": "The hosts introduce the episode and preview the agenda",
  "closing_context": "They wrap up with thanks and sign-off",
  "structure": "Opening banter, news segments, closing recap",
  "overview": "2-4 sentence summary of the entire transcript",
  "key_topics": ["Topic A", "Topic B", "Topic C"],
  "main_topics_detailed": [
    {"title": "Android features", "summary": "The hosts review several new Android updates"}
  ],
  "participants_with_roles": [
    {"name": "Marquez", "role": "host"}
  ],
  "recurring_themes": ["consumer tech", "platform features"],
  "outline": [
    {"title": "Section title", "summary": "What was discussed"}
  ],
  "notable_segments": [
    {"title": "Trivia segment", "summary": "The hosts pivot into a light quiz section"}
  ],
  "action_items": [
    {"owner": "Alice", "task": "Send report", "deadline": "Friday"}
  ],
  "entities": [
    {"name": "Android", "type": "technology"}
  ],
  "_timing": {
    "total_seconds": 87.3,
    "extraction_seconds": 82.1,
    "merge_seconds": 5.2,
    "num_chunks": 34
  }
}
```

## Error Handling

| Scenario | Behavior |
|---|---|
| `with_structured_output` not supported by server | Module flag flips; all future calls use JSON fallback |
| LLM returns malformed JSON | `_empty_chunk_summary()` returned with `_error` field |
| `<think>...</think>` tags in output | Stripped via `RunnableLambda` before JSON parsing |
| Transcript shorter than 2000 tokens | Returned as a single chunk |
| No speaker boundaries in transcript | Hard-cap splits every 4000 tokens |
| All chunk extractions fail | `merge_chunk_summaries([])` returns `_empty_final_summary()` |
| Timing | `_timing` dict appended to result with `total_seconds`, `extraction_seconds`, `merge_seconds`, `num_chunks`; also logged at INFO level |
| Merge payload exceeds model context (e.g. 34 chunks × verbose JSON) | `_compress_for_merge()` keeps only compact discussion points and drops chunk-level entities; if still too large, hierarchical batch merge kicks in |
| All batches fail during hierarchical merge | Returns `_empty_final_summary()` with error |

## Configuration

```python
CHUNK_TARGET_MIN = 2000          # tokens — preferred minimum chunk size
CHUNK_TARGET_MAX = 4000          # tokens — hard cap
CHUNK_OVERLAP_TOKENS = 100       # overlap carried from chunk[i] to chunk[i+1]
MAX_CONCURRENT_EXTRACTIONS = 3   # max parallel LLM calls (semaphore cap)

_MODEL_CONTEXT_SIZE = 32768      # model's context window (tokens)
_MERGE_PROMPT_OVERHEAD = 1200    # reserved for system + human prompt template text
_MERGE_PAYLOAD_BUDGET = 31568    # max tokens for chunk summaries in merge payload
_MERGE_BATCH_SIZE = 8            # summaries per batch in hierarchical merge
```

## Usage

### CLI

```bash
# Summarize a single transcript by ID or filename
python summarize_transcript.py example_transcript_1
python summarize_transcript.py example_transcript_1.srt

# Summarize all transcripts in `transcripts/`
python summarize_transcript.py --all

# Re-summarize even if output already exists:
python summarize_transcript.py --all --force
```

Output is written to `summaries/<transcript_id>.json`. Existing summaries are skipped unless `--force` is passed.

### Async context (e.g. FastAPI endpoint)

```python
from summarize_transcript import summarize_transcript

summary = await summarize_transcript(transcript_text)
print(summary["overview"])
print(summary["action_items"])
```

## Summary Embedding Chunking

The summarization pipeline still produces one canonical summary JSON object and one formatted summary text block for storage and prompt injection. What changed is the vector-store representation of that summary for retrieval and embedding.

### Why this was needed

Originally, uploaded transcript ingestion embedded the full formatted summary as a single `Document`. That caused two problems:

- large summaries could exceed the embedding service input limits
- one monolithic summary vector was too coarse for topic-level retrieval

The summary embedding path now uses semantic chunking before embedding.

### Current behavior

Implemented in:

- [src/document_processor.py](/Users/tohkarle/Desktop/Coding/Python/LangChain/src/document_processor.py)
- [src/uploaded_transcript_service.py](/Users/tohkarle/Desktop/Coding/Python/LangChain/src/uploaded_transcript_service.py)
- [src/rag_initializer.py](/Users/tohkarle/Desktop/Coding/Python/LangChain/src/rag_initializer.py)

For each uploaded transcript summary, ingestion now creates multiple summary embedding documents instead of one:

1. `overview`
- upload/publication date
- participants / roles
- conversation type / purpose
- overview
- key topics

2. `topic`
- one document per `main_topics_detailed` item

3. `outline`
- one document per `outline` item

4. `segment`
- one document per `notable_segments` item

5. `actions`
- one or more documents for `action_items`

6. `entities`
- one document for the `entities` list when present

7. `misc`
- fallback document for additional summary fields not covered above

Each summary embedding document has:

- `content_type="summary"`
- `summary_chunk_type`
- `summary_chunk_index`
- `summary_parent_id`
- upload/date metadata
- deterministic ids such as:
  - `transcript_id:summary:overview`
  - `transcript_id:summary:topic:0`
  - `transcript_id:summary:outline:0`

### Important boundary: transcript chunking vs summary embedding chunking

This does **not** change transcript content chunking.

- transcript content chunks still come from the SRT chunk pipeline
- DB chunk rows and API `chunk_count` still reflect those original transcript chunks
- only summary embedding documents are chunked semantically

### Embedding safety split

There is also an embedding-safety split for oversized documents, but it now applies only to summary documents.

- transcript content chunks are not modified by `EMBEDDING_MAX_TEXT_CHARS`
- summary docs are first split semantically by section
- only if an individual summary section is still too large does the embedding path split it further before calling the embedding service

This preserves transcript chunk boundaries while protecting summary embedding from model input limits.

### Retrieval impact

- summary documents remain retrievable through the normal vector/BM25/rerank pipeline
- route-aware chronology reconstruction still excludes summary docs
- prompt-injected transcript summaries still come from the single canonical summary stored in the DB
- broad and topic-style queries can now hit focused summary sections instead of one coarse summary blob

### Sync context

```python
import asyncio
from summarize_transcript import summarize_transcript

with open("transcripts/example_transcript_1.srt") as f:
    text = f.read()

result = asyncio.run(summarize_transcript(text))
```

### Jupyter notebook

```python
import nest_asyncio
nest_asyncio.apply()   # required in Jupyter
import asyncio
from summarize_transcript import summarize_transcript

result = asyncio.run(summarize_transcript(text))
```

## Dependencies

```
langchain==1.0.2
langchain-openai==1.0.1
langchain-core==1.2.1
pydantic==2.12.5
```

Local Qwen LLM must be running at `http://localhost:8080/v1`.

## Design Decisions

| Decision | Choice | Reason |
|---|---|---|
| Structured output method | `with_structured_output()` with JSON fallback | Protocol-level enforcement is more reliable; fallback ensures compatibility with older llama.cpp builds |
| Final merge compression | Keep compact `discussion_points`, drop chunk-level `entities` | Preserves more global signal while staying within 32k merge budget |
| Richer transcript schema | `main_topics_detailed`, `participants_with_roles`, `recurring_themes`, `notable_segments` | Gives route-aware RAG better transcript maps for broad questions |
| LLM factory | New `get_local_llm()` in `rag_config.py` | Decoupled from `ANSWER_MODEL` setting; existing factory raises if DeepSeek credentials are missing |
| Overlap implementation | Reuse `extract_last_n_tokens()` from `document_processor.py` | Avoids duplication; token-accurate with encode/decode, character fallback chain |
| Prompt location | `prompt_templates.py` | Follows project convention; all prompts in one place |
| Async concurrency | `asyncio.Semaphore(3)` + `asyncio.gather()` | Limits memory pressure on single-threaded local model; non-blocking for caller |
| `streaming=False` | Required on `get_local_llm()` | `with_structured_output()` and `JsonOutputParser` need the complete response |
| Merge compression | Strip `discussion_points` + `entities` before merge | These fields are chunk-level detail not needed for synthesis; reduces payload ~50% (9075 → ~3000 tokens for 34 chunks) |
| Hierarchical merge | Batch → intermediate results → final merge | Handles transcripts too long even after compression; avoids losing all extracted data on context overflow |
