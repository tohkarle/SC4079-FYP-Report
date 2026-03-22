# Search Bar Implementation

## Overview

A **keyword-first search interface** for finding specific transcript snippets. Complements the existing chatbot (conversational Q&A) with fast, Google-like search.

**Key Difference**: Search bar prioritizes exact keyword matching (BM25), while chatbot prioritizes semantic understanding.

---

## Quick Start

```bash
# Basic search
python3 search_bar.py "Samsung"

# With date filter
python3 search_bar.py "regrets" --date "last friday"

# With speaker filter
python3 search_bar.py "AI" --speaker "Host"

# Combined filters
python3 search_bar.py "technology" --date "December 2024" --speaker "Guest"

# JSON output
python3 search_bar.py "Samsung" --json

# Debug mode
python3 search_bar.py "Samsung" --verbose
```

---

## Architecture

### Search Bar vs Chatbot

| Aspect | **Search Bar** | **Chatbot** |
|--------|---------------|------------|
| **Use Case** | Find specific snippets | Answer questions |
| **BM25 Weight** | 3.0 (keyword priority) | 1.0 |
| **Semantic Weight** | 1.0 | 1.0 |
| **Signals Used** | BM25 + Semantic + Phonetic + Fuzzy | BM25 + Semantic + Phonetic + Fuzzy |
| **Reranking** | On by default (Phase 2 corpus is small) | On (accuracy) |
| **Neighbor Expansion** | No (direct chunks) | Optional (context) |
| **Result Shape** | Grouped by transcript (top 3 × top 5 chunks) | Flat ranked list |

### Retrieval Pipeline

```
User Query: "Samsung"
    ↓
[Parse Filters]
├─ Keywords: "Samsung"
├─ Date: (optional)
└─ Speaker: (optional)
    ↓
─── PHASE 1: Transcript Ranking ────────────────────────────
│   [If date filter active: pre-compute date-matched transcript
│    IDs from all Chroma summary doc metadata — independent of
│    retrieval scores so no transcript is missed]
│       ↓
│   [Parallel Retrieval — all transcripts, no reranking]
│   ├─ BM25 Search (k=20, weight=3.0)
│   ├─ Semantic Search (k=10, weight=1.0)
│   ├─ Phonetic Search (k=10, weight=0.2)
│   └─ Fuzzy Search (k=10, weight=0.2)
│       ↓
│   [RRF Fusion]
│       ↓
│   [Keep only summary chunks (content_type == "summary")]
│   └─ Summary chunks represent the transcript as a whole,
│      giving a clean transcript-level relevance signal
│       ↓
│   [Aggregate summary chunk scores per transcript]
│   └─ transcript_score = sum(top 3 summary chunk fusion scores)
│       ↓
│   [Select transcripts for Phase 2]
│   ├─ No date filter: top 3 by relevance score
│   └─ Date filter active: ALL date-matched transcripts,
│      ordered by relevance score (no top-3 cap)
────────────────────────────────────────────────────────────
    ↓
─── PHASE 2: Per-Transcript Chunk Search ───────────────────
│   For each selected transcript:
│   [Parallel Retrieval — scoped to this transcript]
│       ↓
│   [RRF Fusion]
│       ↓
│   [Exclude summary chunks (content_type != "summary")]
│   └─ Only real transcript content chunks are returned
│       ↓
│   [Cross-encoder Reranking (top 5)]
│       ↓
│   [Post-fusion Metadata Filtering]
│   ├─ Filter by date range (safety net — already pre-filtered)
│   └─ Filter by speaker (if provided)
│       ↓
│   [Top 5 chunks for this transcript]
────────────────────────────────────────────────────────────
    ↓
[Return grouped_results]
└─ Up to N transcripts × up to 5 chunks each
   (N = 3 without date filter; all date-matched with date filter)
```

**Why Filtering Approach?**
- Users searching for a topic want to see which transcripts are relevant, not a flat list of chunks
- Grouping by transcript gives context: "this transcript has 4 strong matches"
- Phase 1 finds transcripts efficiently without expensive reranking
- Phase 2 runs on a small corpus (1 transcript at a time), so reranking is cheap

**Why summary chunks in Phase 1, content chunks in Phase 2?**
- Summary chunks (`content_type == "summary"`) describe the transcript at a high level — they give a clean transcript-level relevance signal without mixing in low-level content
- Content chunks (`content_type != "summary"`) contain the actual timestamped transcript text that users want to read — summaries appearing in the top-5 results would be misleading

**Why Keyword-First?**
- Users expect exact term matching for brand names (Samsung, Apple)
- Better for proper nouns, technical terms, acronyms
- BM25 excels at finding specific mentions
- Semantic search provides fallback for related concepts

---

## Files

| File | Purpose |
|------|---------|
| `search_bar.py` | Main CLI interface |
| `search_bar_config.py` | Search bar-specific configuration (weights, toggles, top-k) |
| `rag_retriever.py` | `retrieve_for_search_bar()` function |
| `retrieval_core.py` | Reusable retrieval building blocks |
| `date_parser.py` | Natural language date parsing |

---

## Configuration

In `search_bar_config.py`:

```python
TOP_K_RESULTS = 15               # Passed through from request (not directly applied)
ENABLE_RERANKING = True          # Enabled — Phase 2 corpus is small so overhead is low
RERANKER_TOP_N = 5               # Chunks kept per transcript after reranking
TOP_TRANSCRIPTS = 3              # Phase 1: transcripts selected for Phase 2
CHUNKS_PER_TRANSCRIPT = 5        # Phase 2: max chunks returned per transcript
BM25_WEIGHT = 3.0                # Keyword priority (3x vs chatbot's 1.0)
VECTOR_WEIGHT = 1.0              # Semantic search weight
PHONETIC_ENABLED = True          # Sound-alike matching
FUZZY_ENABLED = True             # Edit-distance matching
NEIGHBOR_CHUNKS_ENABLED = False  # Direct snippets only (no context expansion)
```

---

## Date Filtering

### Supported Formats

```bash
# Relative dates
--date "last friday"
--date "yesterday"
--date "this week"

# Month/Year
--date "December 2024"
--date "2024"

# ISO dates
--date "2024-12-27"
```

### How It Works

1. `parse_date_query()` converts natural language to datetime range
2. Before Phase 1: queries Chroma metadata to find all transcript IDs whose `upload_date` falls in range — this is independent of retrieval scores so no transcript is missed regardless of `TOP_TRANSCRIPTS` cap
3. Phase 1 result: only date-matched transcripts are forwarded to Phase 2 (ordered by relevance score)
4. Phase 2: `filter_by_date_range()` is also applied post-fusion as a safety net, and filters chunks by `upload_date` metadata

---

## Speaker Filtering

### Usage

```bash
# Single speaker
python3 search_bar.py "AI" --speaker "Host"

# Multiple speakers
python3 search_bar.py "technology" --speaker "Host,Guest"
```

### How It Works

1. Requires speaker names in `transcript_metadata.json`
2. Maps speaker markers (`speaker_0`, `speaker_1`) to actual names
3. Filters documents by `speaker_name` metadata field

---

## Command-Line Options

```
usage: search_bar.py [-h] [--date DATE] [--speaker SPEAKER]
                     [--transcripts TRANSCRIPTS] [--top-k TOP_K]
                     [--rerank] [--json] [--verbose]
                     query

Arguments:
  query                   Search keywords (required)

Options:
  --date DATE            Date filter (natural language)
  --speaker SPEAKER      Speaker name(s), comma-separated
  --transcripts IDS      Transcript IDs, comma-separated
  --top-k N              Number of results (default: 15)
  --rerank               Enable cross-encoder reranking (slower)
  --json                 Output as JSON
  --verbose              Print debug info
```

---

## Output Format

### Terminal Output

```
================================================================================
Found 15 results in 24ms
================================================================================

[1] example_transcript_2 @ 00:25:40 -> 00:26:02
    Speaker: Guest
    Date: 2024-12-21
    Score: 0.049
    They should have just called it the Samsung Galaxy brochure...

[2] example_transcript_2 @ 00:26:54 -> 00:27:17
    Score: 0.048
    So we'll see. Ironically cuz usually the telephoto is the worst...
```

### JSON Output

```json
{
  "grouped_results": [
    {
      "transcript_id": "example_transcript_2",
      "source_filename": "example_transcript_2.srt",
      "upload_date": "2024-12-21",
      "transcript_relevance_score": 0.134,
      "chunks": [
        {
          "chunk_id": "42",
          "text": "Samsung announced...",
          "speaker": "Guest",
          "timestamp": "00:25:40 -> 00:26:02",
          "relevance_score": 0.049
        }
      ]
    }
  ],
  "total_results": 3,
  "query_time_ms": 180,
  "filters_applied": {
    "date_range": false,
    "date_range_parsed": null,
    "speaker": false,
    "transcripts": false
  }
}
```

---

## Code Structure

### Main Function: `retrieve_for_search_bar()`

Located in `rag_retriever.py`. Defaults are read from `search_bar_config.py` at call time.

```python
def retrieve_for_search_bar(
    vector_retriever,
    bm25_retriever,
    query: str,
    date_filter: Optional[dict] = None,           # {"start": datetime, "end": datetime}
    speaker_filter: Optional[List[str]] = None,
    transcript_filters: Optional[List[str]] = None,  # if set, skips Phase 1
    top_k: int = 15,
    enable_reranking: Optional[bool] = None,      # defaults to search_bar_config.ENABLE_RERANKING
    reranker = None,
    reranker_top_n: Optional[int] = None,         # defaults to search_bar_config.RERANKER_TOP_N
    top_transcripts: Optional[int] = None,        # defaults to search_bar_config.TOP_TRANSCRIPTS
    chunks_per_transcript: Optional[int] = None,  # defaults to search_bar_config.CHUNKS_PER_TRANSCRIPT
    phonetic_indexer = None,
    fuzzy_matcher = None,
    verbose: bool = False
) -> dict
```

**Returns:**
```python
{
    'grouped_results': [
        {
            'transcript_id': str,
            'source_filename': str,
            'upload_date': Optional[str],
            'transcript_relevance_score': float,   # sum of top-3 Phase 1 chunk fusion scores
            'chunks': [
                {
                    'chunk_id': Optional[str],
                    'text': str,
                    'speaker': Optional[str],
                    'timestamp': str,              # "HH:MM:SS -> HH:MM:SS"
                    'relevance_score': float,      # reranker score or fusion score
                }
            ]
        }
    ],
    'total_results': int,       # sum of chunk counts across all grouped results
    'query_time_ms': int,
    'filters_applied': dict     # {'date_range': bool, 'date_range_parsed': ... | None, 'speaker': bool, 'transcripts': bool}
}
```

### Reusable Functions in `retrieval_core.py`

```python
filter_by_date_range(documents, start_date, end_date)
filter_by_speaker(documents, speaker_names)
```

These are shared by both search bar and chatbot (no code duplication).

---

## Performance

### Target Performance

| Stage | Target |
|-------|--------|
| Phase 1 — global retrieval + aggregation | 100-250ms |
| Phase 2 — per-transcript retrieval × 3 | 150-300ms |
| Phase 2 — reranking × 3 (small corpus) | 50-150ms |
| Filtering | 5-10ms |
| **Total** | **300-700ms** |

Phase 1 runs without reranking to keep latency low. Phase 2 reranking is cheap because each pass covers only one transcript's chunks.

---

## Integration

### REST API

The search bar is also accessible as a REST endpoint (see `API_IMPLEMENTATION.md`):

```bash
curl -X POST http://localhost:8083/api/search \
  -H "Content-Type: application/json" \
  -d '{"query": "Samsung", "date": "last friday", "speaker": "Host", "top_k": 15}'
```

### Using in Python Code

```python
from rag_initializer import RAGInitializer
from rag_retriever import retrieve_for_search_bar
from date_parser import parse_date_query

# Initialize
rag = RAGInitializer()
rag.initialize_embeddings()
rag.load_global_vector_store()
retriever = rag.get_retriever()
components = rag.initialize_retrieval_components()
bm25 = components['bm25_retriever']
phonetic = components['phonetic_indexer']
fuzzy = components['fuzzy_matcher']

# Parse date filter
date_range = parse_date_query("last friday")
date_filter = {"start": date_range[0], "end": date_range[1]}

# Search
results = retrieve_for_search_bar(
    vector_retriever=retriever,
    bm25_retriever=bm25,
    query="Samsung",
    date_filter=date_filter,
    speaker_filter=["Host"],
    phonetic_indexer=phonetic,
    fuzzy_matcher=fuzzy,
)

# Use results
for group in results['grouped_results']:
    print(f"{group['transcript_id']} (score={group['transcript_relevance_score']:.3f})")
    for chunk in group['chunks']:
        print(f"  [{chunk['timestamp']}] {chunk['text'][:80]}")
```

---

## Troubleshooting

### No results found

**Check:**
1. Is date range correct? Use `--verbose` to see the parsed date range
2. Try the search without filters first
3. Check that `upload_date` metadata is populated in the vector store for date filtering to work

### Slow performance (>500ms)

**Causes:**
- Reranking enabled (`--rerank`) — adds 300-800ms
- Large result set — reduce `--top-k`

---

---

## Testing

### Manual Testing

```bash
# Test basic search
python3 search_bar.py "Samsung"

# Test date parsing
python3 search_bar.py "phone" --date "last friday" --verbose

# Test speaker filter
python3 search_bar.py "AI" --speaker "Host" --verbose

# Test JSON output
python3 search_bar.py "Samsung" --json | python3 -m json.tool
```

### Unit Tests

Run tests (if implemented):
```bash
pytest tests/test_retrieval_core.py
pytest tests/test_date_parser.py
```

---

## Dependencies

New dependencies added:
```bash
pip install dateparser
```

Existing dependencies used:
- langchain
- chromadb
- rank-bm25
- rapidfuzz (optional, for fuzzy matching)

---

## Summary

**What**: Two-phase keyword-first search returning results grouped by transcript

**Why**: Users want to see which transcripts are relevant and browse the top hits within each — not scroll through a flat list of chunks from unknown sources

**How**: Phase 1 ranks transcripts via BM25-prioritized retrieval + score aggregation; Phase 2 runs per-transcript search with reranking and date/speaker filtering

**When to use**: Finding brand mentions, quotes, topics, speakers, or content from specific dates

**When NOT to use**: Complex questions requiring reasoning → use chatbot instead
