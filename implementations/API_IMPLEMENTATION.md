# FastAPI Uploaded Transcript API

## Overview

This document describes the current FastAPI API implementation for the uploaded-transcript RAG runtime.

- Server URL: `http://localhost:8083`
- Primary runtime corpus: uploaded transcripts
- Evaluation/example transcripts remain separate and are not the primary API data source
- Main implementation files:
  - [src/api.py](/Users/tohkarle/Desktop/Coding/Python/LangChain/src/api.py)
  - [src/models.py](/Users/tohkarle/Desktop/Coding/Python/LangChain/src/models.py)
  - [src/uploaded_transcript_repository.py](/Users/tohkarle/Desktop/Coding/Python/LangChain/src/uploaded_transcript_repository.py)
  - [src/uploaded_transcript_service.py](/Users/tohkarle/Desktop/Coding/Python/LangChain/src/uploaded_transcript_service.py)

## Runtime Dependencies

- Local LLM service: `http://localhost:8080/v1`
- Embedding service: `http://localhost:8081/v1`
- Reranker service: `http://localhost:8082`
- FastAPI server: `http://localhost:8083`
- Uploaded transcript metadata store: SQLite database under `data/uploaded_transcripts.db`
- Uploaded transcript vector store: `vector_stores/uploaded_transcripts`

## Authentication / Headers / Content Types

- Authentication: none
- Default content type: `application/json`
- Upload endpoint content type: `multipart/form-data`
- No custom headers are required for normal usage

## Data Models

### `ChatRequest`

Used by `POST /api/chat`.

- `session_id` required string: conversation session identifier
- `message` required string: user question or follow-up message
- `transcript_filter` optional string: uploaded transcript id to scope retrieval
- `include_sources` optional boolean, default `true`: whether to include citations

### `ChatResponse`

Returned by `POST /api/chat`.

- `session_id` string: session identifier
- `answer` string: generated answer
- `sources` optional array of `SourceMetadata`
- `retrieval_info` optional `RetrievalInfo`
- `turn_count` integer: number of completed turns in the session

### `QueryRequest`

Used by `POST /api/query`.

- `question` required string: one-off user query
- `transcript_filter` optional string: uploaded transcript id to scope retrieval
- `include_sources` optional boolean, default `true`

### `QueryResponse`

Returned by `POST /api/query`.

- `answer` string
- `sources` optional array of `SourceMetadata`
- `retrieval_info` optional `RetrievalInfo`

### `TranscriptInfo`

Returned inside `GET /api/transcripts`.

- `transcript_id` string
- `source_filename` string
- `chunk_count` integer
- `upload_date` optional string in `YYYY-MM-DD`
- `upload_timestamp` optional ISO timestamp
- `processing_status` optional string

### `TranscriptListResponse`

- `transcripts` array of `TranscriptInfo`
- `total_count` integer

### `TranscriptUploadResponse`

Returned by `POST /api/transcripts/upload`.

- `transcript_id` string
- `source_filename` string
- `chunk_count` integer
- `upload_date` string in `YYYY-MM-DD`
- `upload_timestamp` ISO timestamp
- `processing_status` string

### `TranscriptSummaryResponse`

Returned by `GET /api/transcripts/{transcript_id}/summary`.

- `transcript_id` string
- `source_filename` string
- `upload_date` string in `YYYY-MM-DD`
- `upload_timestamp` ISO timestamp
- `summary` object: stored summary JSON payload

### `TranscriptContentResponse`

Returned by `GET /api/transcripts/{transcript_id}/content`.

- `transcript_id` string
- `source_filename` string
- `upload_date` string in `YYYY-MM-DD`
- `upload_timestamp` ISO timestamp
- `raw_text` string: full stored transcript text

### `SourceMetadata`

Returned in `sources` arrays for query/chat responses.

- `chunk_number` integer: position in the source list
- `chunk_id` string or integer: chunk identifier
- `preview` string: short text preview
- `full_text` string: full retrieved chunk text
- `source` string: source filename
- `transcript_id` string: uploaded transcript id
- `start_time` string: transcript time range start
- `end_time` string: transcript time range end
- `speaker` optional string
- `rerank_score` optional float

### `RetrievalInfo`

Returned in query/chat responses.

- `used_hybrid` boolean
- `vector_count` integer
- `bm25_count` integer
- `fused_count` integer
- `final_count` integer
- `used_neighbors` boolean
- `reranked` boolean

### `SearchRequest`

Used by `POST /api/search`.

- `query` required string: search keywords (not a natural language question)
- `date` optional string: date filter in natural language — `"last friday"`, `"December 2024"`, `"2024-12-27"`
- `speaker` optional string: speaker name(s), comma-separated for multiple
- `transcripts` optional string: transcript IDs to scope the search, comma-separated (skips Phase 1 transcript ranking when provided)
- `top_k` optional integer, default `15`: passed through but not directly applied; Phase 2 uses `CHUNKS_PER_TRANSCRIPT` per transcript
- `rerank` optional boolean, default `false`: set `true` to explicitly force reranking; reranking is now enabled by default via `search_bar_config.ENABLE_RERANKING`

### `ChunkResult`

A single chunk nested inside a `GroupedTranscriptResult`.

- `chunk_id` optional string: unique chunk identifier
- `text` string: chunk text content
- `speaker` optional string: speaker name if available
- `timestamp` string: time range formatted as `"start -> end"`
- `relevance_score` float: reranker score if reranking was applied, otherwise RRF fusion score

### `GroupedTranscriptResult`

- `transcript_id` string: transcript identifier
- `source_filename` string: original source filename
- `upload_date` optional string: transcript upload date in `YYYY-MM-DD`
- `transcript_relevance_score` float: aggregated relevance score for this transcript (sum of top-3 chunk fusion scores from Phase 1)
- `chunks` array of `ChunkResult`: top matching chunks within this transcript

### `SearchResponse`

Returned by `POST /api/search`.

- `grouped_results` array of `GroupedTranscriptResult`: up to 3 transcripts without a date filter; all date-matched transcripts when a date filter is active — each with up to 5 nested chunks
- `total_results` integer: total number of chunks across all grouped results
- `query_time_ms` integer
- `filters_applied` object: `{ "date_range": bool, "date_range_parsed": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"} | null, "speaker": bool, "transcripts": bool }`

### `HealthResponse`

Returned by `GET /api/health`.

- `status` string: `healthy` or `unhealthy`
- `rag_initialized` boolean
- `services` object: service availability map
- `vector_store_chunks` optional integer
- `message` optional string

### `SessionDeleteResponse`

- `session_id` string
- `deleted` boolean
- `message` string

### `SessionListResponse`

- `sessions` array of strings
- `total_count` integer

## Endpoint Reference

### `GET /`

Purpose: basic service metadata.

Arguments:
- none

Returns:
- `message`
- `version`
- `docs`
- `redoc`
- `health`

Example response:

```json
{
  "message": "RAG Q&A Service",
  "version": "1.0.0",
  "docs": "/docs",
  "redoc": "/redoc",
  "health": "/api/health"
}
```

Typical errors:
- none in normal operation

### `GET /api/health`

Purpose: check whether the API runtime and upstream dependencies are available.

Arguments:
- none

Returns:
- `status`
- `rag_initialized`
- `services.embedding`
- `services.llm`
- `services.reranker`
- `services.bm25`
- `vector_store_chunks`
- `message`

Example response:

```json
{
  "status": "healthy",
  "rag_initialized": true,
  "services": {
    "embedding": "available",
    "llm": "available",
    "reranker": "available",
    "bm25": "available"
  },
  "vector_store_chunks": 27,
  "message": "All systems operational"
}
```

Typical errors:
- none; unhealthy state is returned in the body rather than as an HTTP error

### `GET /api/transcripts`

Purpose: list uploaded transcripts known to the API runtime.

Arguments:
- none

Returns:
- `transcripts`: array of `TranscriptInfo`
- `total_count`

Example response:

```json
{
  "transcripts": [
    {
      "transcript_id": "sample_small_20260321_233803",
      "source_filename": "sample_small.srt",
      "chunk_count": 8,
      "upload_date": "2026-03-21",
      "upload_timestamp": "2026-03-21T23:38:03.030448",
      "processing_status": "completed"
    }
  ],
  "total_count": 1
}
```

Typical errors:
- `503` if the RAG runtime or transcript repository is not initialized
- `500` if listing fails internally

### `POST /api/transcripts/upload`

Purpose: upload a new `.srt` file and process it through parsing, chunking, summarization, persistence, and indexing.

Content type:
- `multipart/form-data`

Arguments:
- required form field `file`: uploaded `.srt` file

Returns:
- `transcript_id`
- `source_filename`
- `chunk_count`
- `upload_date`
- `upload_timestamp`
- `processing_status`

Example request:

```bash
curl -X POST http://localhost:8083/api/transcripts/upload \
  -F "file=@tests/test_data/sample_small.srt"
```

Example response:

```json
{
  "transcript_id": "sample_small_20260321_233803",
  "source_filename": "sample_small.srt",
  "chunk_count": 8,
  "upload_date": "2026-03-21",
  "upload_timestamp": "2026-03-21T23:38:03.030448",
  "processing_status": "completed"
}
```

Typical errors:
- `400` if the file is missing, empty, or does not end with `.srt`
- `503` if the upload service is not initialized
- `500` if parsing, summarization, persistence, or indexing fails

### `GET /api/transcripts/{transcript_id}/summary`

Purpose: fetch the stored summary JSON for one uploaded transcript.

Path arguments:
- `transcript_id` required string

Returns:
- `transcript_id`
- `source_filename`
- `upload_date`
- `upload_timestamp`
- `summary`: stored summary payload

Example response:

```json
{
  "transcript_id": "sample_small_20260321_233803",
  "source_filename": "sample_small.srt",
  "upload_date": "2026-03-21",
  "upload_timestamp": "2026-03-21T23:38:03.030448",
  "summary": {
    "transcript_id": "sample_small_20260321_233803",
    "source": "sample_small.srt",
    "upload_timestamp": "2026-03-21T23:38:03.030448",
    "upload_date": "2026-03-21",
    "overview": "A conversation about hobbies and interests, discussing reading, computer games, and sports.",
    "key_topics": ["Reading", "Computer games", "Sports"]
  }
}
```

Typical errors:
- `404` if the transcript id is unknown
- `404` if the transcript exists but no summary is stored
- `503` if the transcript repository is not initialized

### `GET /api/transcripts/{transcript_id}/content`

Purpose: fetch the stored raw transcript text for one uploaded transcript.

Path arguments:
- `transcript_id` required string

Returns:
- `transcript_id`
- `source_filename`
- `upload_date`
- `upload_timestamp`
- `raw_text`

Example response:

```json
{
  "transcript_id": "sample_small_20260321_233803",
  "source_filename": "sample_small.srt",
  "upload_date": "2026-03-21",
  "upload_timestamp": "2026-03-21T23:38:03.030448",
  "raw_text": "Hello and welcome to the conversation..."
}
```

Typical errors:
- `404` if the transcript id is unknown
- `503` if the transcript repository is not initialized

### `POST /api/search`

Purpose: keyword-first transcript search returning results grouped by transcript (not generated answers).

Behavior:
- **Phase 1 — transcript ranking**: runs the full retrieval pipeline (BM25 + semantic + phonetic + fuzzy + RRF) over all transcripts without reranking; keeps only summary chunks (`content_type == "summary"`) and aggregates their scores per transcript (sum of top-3 fusion scores). When a date filter is active, all transcripts whose `upload_date` falls in the date range are forwarded to Phase 2 (ordered by relevance score, no top-3 cap). Without a date filter, only the top 3 transcripts are selected. Skipped when `transcripts` filter is provided.
- **Phase 2 — chunk search**: re-runs the pipeline scoped to each selected transcript; excludes summary chunks (`content_type != "summary"`), applies reranking, date/speaker filters, and returns the top 5 content chunks per transcript.
- BM25-prioritized hybrid retrieval (BM25 weight 3.0 vs semantic 1.0)
- Date filter applied in Phase 1 (transcript selection) and as a post-fusion safety net in Phase 2; speaker filter applied post-fusion in Phase 2
- No neighbor chunk expansion — returns direct snippets
- Reranking enabled by default (Phase 2 corpus is small so overhead is low); can be disabled per-request via `rerank: false`

Arguments:
- `query` required string
- `date` optional string
- `speaker` optional string
- `transcripts` optional string: scopes search to specific transcripts and skips Phase 1
- `top_k` optional integer, default `15`
- `rerank` optional boolean: overrides the config default when explicitly set

Returns:
- `grouped_results` array of `GroupedTranscriptResult`
- `total_results`
- `query_time_ms`
- `filters_applied`

Example request:

```json
{
  "query": "Samsung",
  "date": "last friday",
  "speaker": "Host",
  "top_k": 15
}
```

Example response:

```json
{
  "grouped_results": [
    {
      "transcript_id": "example_transcript_2_20260322_162807",
      "source_filename": "example_transcript_2.srt",
      "upload_date": "2026-03-22",
      "transcript_relevance_score": 0.134,
      "chunks": [
        {
          "chunk_id": "83",
          "text": "they put a screen protector on it or whatever...",
          "speaker": null,
          "timestamp": "00:35:55,920 -> 00:36:21,359",
          "relevance_score": 0.049
        }
      ]
    }
  ],
  "total_results": 3,
  "query_time_ms": 180,
  "filters_applied": {
    "date_range": true,
    "date_range_parsed": {"start": "2026-03-18", "end": "2026-03-22"},
    "speaker": true,
    "transcripts": false
  }
}
```

Typical errors:
- `400` if the `date` string cannot be parsed (e.g. unrecognisable format)
- `503` if the RAG runtime is not initialized
- `500` if retrieval fails

### `POST /api/query`

Purpose: perform a stateless, transcript-scoped or unscoped query.

Behavior:
- Uses route-aware retrieval
- May inject both `transcript_summary` and `route_instructions` into the prompt
- Public API accepts one `transcript_filter`
- Internally this is converted to `transcript_filters=[transcript_filter]`

Arguments:
- `question` required string
- `transcript_filter` optional string
- `include_sources` optional boolean, default `true`

Returns:
- `answer`
- `sources` optional array of `SourceMetadata`
- `retrieval_info` optional `RetrievalInfo`

Example request:

```json
{
  "question": "What hobbies are mentioned in this transcript?",
  "transcript_filter": "sample_small_20260321_233803",
  "include_sources": true
}
```

Example response:

```json
{
  "answer": "The hobbies mentioned in the transcript are reading, computer games, and sports.",
  "sources": [
    {
      "chunk_number": 1,
      "chunk_id": "5",
      "preview": "Reading is my favorite hobby.",
      "full_text": "Reading is my favorite hobby.",
      "source": "sample_small.srt",
      "transcript_id": "sample_small_20260321_233803",
      "start_time": "00:00:13,000",
      "end_time": "00:00:16,000",
      "speaker": null,
      "rerank_score": null
    }
  ],
  "retrieval_info": {
    "used_hybrid": true,
    "vector_count": 9,
    "bm25_count": 9,
    "fused_count": 9,
    "final_count": 9,
    "used_neighbors": false,
    "reranked": false
  }
}
```

Typical errors:
- `503` if the RAG runtime is not initialized
- `500` if retrieval or answer generation fails

### `POST /api/chat`

Purpose: perform multi-turn transcript QA with session state.

Behavior:
- Uses route-aware retrieval
- Injects `transcript_summary` and `route_instructions` when available
- Maintains in-memory session history through `session_id`
- Public API accepts one `transcript_filter`
- Internally this is converted to `transcript_filters=[transcript_filter]`

Arguments:
- `session_id` required string
- `message` required string
- `transcript_filter` optional string
- `include_sources` optional boolean, default `true`

Returns:
- `session_id`
- `answer`
- `sources` optional array of `SourceMetadata`
- `retrieval_info` optional `RetrievalInfo`
- `turn_count`

Example request:

```json
{
  "session_id": "smoke-session-1",
  "message": "What hobbies are mentioned?",
  "transcript_filter": "sample_small_20260321_233803",
  "include_sources": true
}
```

Example response:

```json
{
  "session_id": "smoke-session-1",
  "answer": "The hobbies mentioned are reading, computer games, and sports.",
  "sources": [
    {
      "chunk_number": 1,
      "chunk_id": "5",
      "preview": "Reading is my favorite hobby.",
      "full_text": "Reading is my favorite hobby.",
      "source": "sample_small.srt",
      "transcript_id": "sample_small_20260321_233803",
      "start_time": "00:00:13,000",
      "end_time": "00:00:16,000",
      "speaker": null,
      "rerank_score": null
    }
  ],
  "retrieval_info": {
    "used_hybrid": true,
    "vector_count": 9,
    "bm25_count": 9,
    "fused_count": 9,
    "final_count": 9,
    "used_neighbors": false,
    "reranked": false
  },
  "turn_count": 1
}
```

Typical errors:
- `503` if the RAG runtime is not initialized
- `500` if retrieval, session update, or answer generation fails

### `POST /api/chat/stream`

Purpose: perform multi-turn transcript QA with incremental server-sent-event streaming for the Ask AI UI.

Behavior:
- Uses the same request body as `POST /api/chat`
- Uses the same route-aware retrieval, transcript summary injection, and transcript filter scoping as `POST /api/chat`
- Streams partial assistant text as it is generated
- Commits the turn to session history only after successful completion
- Sends sources and retrieval metadata only in the final `done` event

Headers:
- Request `Content-Type: application/json`
- Request `Accept: text/event-stream`
- Response `Content-Type: text/event-stream`

Arguments:
- `session_id` required string
- `message` required string
- `transcript_filter` optional string
- `include_sources` optional boolean, default `true`

Event stream:
- `start`
  - payload: `{ "session_id": "..." }`
- `token`
  - payload: `{ "delta": "..." }`
- `done`
  - payload: full `ChatResponse` JSON
- `error`
  - payload: `{ "detail": "..." }`

Example request:

```json
{
  "session_id": "smoke-session-1",
  "message": "Summarize the work culture points.",
  "transcript_filter": "example_transcript_4_20260322_163815",
  "include_sources": false
}
```

Example event stream:

```text
event: start
data: {"session_id":"smoke-session-1"}

event: token
data: {"delta":"The transcript discusses"}

event: token
data: {"delta":" workplace culture, leadership, and growth opportunities."}

event: done
data: {"session_id":"smoke-session-1","answer":"The transcript discusses workplace culture, leadership, and growth opportunities.","sources":null,"retrieval_info":{"used_hybrid":true,"vector_count":9,"bm25_count":9,"fused_count":9,"final_count":9,"used_neighbors":false,"reranked":false},"turn_count":1}
```

Typical errors:
- `503` if the RAG runtime is not initialized
- `error` SSE event if retrieval or answer generation fails after the stream starts

### `GET /api/sessions`

Purpose: list active in-memory chat sessions.

Arguments:
- none

Returns:
- `sessions`: array of session ids
- `total_count`

Example response:

```json
{
  "sessions": ["smoke-session-1", "user123-conv456"],
  "total_count": 2
}
```

Typical errors:
- none in normal operation

### `DELETE /api/sessions/{session_id}`

Purpose: delete one in-memory chat session.

Path arguments:
- `session_id` required string

Returns:
- `session_id`
- `deleted`
- `message`

Example response:

```json
{
  "session_id": "smoke-session-1",
  "deleted": true,
  "message": "Session deleted successfully"
}
```

Typical errors:
- none in normal operation; a missing session returns `deleted=false`

## Uploaded Transcript Processing Flow

After `POST /api/transcripts/upload`, the server processes the transcript in this order:

1. Read the uploaded `.srt` file.
2. Parse the transcript text and SRT chunks.
3. Create chunk documents with uploaded-transcript metadata.
4. Run the transcript through the summarization pipeline.
5. Store transcript metadata in SQLite.
6. Store transcript chunks in SQLite.
7. Store summary JSON and flattened summary text in SQLite.
8. Embed chunk documents and semantic summary documents into the uploaded vector store.
9. Rebuild BM25 and phonetic indexes for the uploaded corpus.
10. Return transcript metadata to the caller.

## Error Handling

Current API error patterns:

- `400 Bad Request`
  - non-`.srt` upload
  - empty upload
  - unparseable `date` string in `/api/search`
- `404 Not Found`
  - unknown transcript id for summary lookup
  - transcript exists but summary is missing
- `503 Service Unavailable`
  - RAG runtime not initialized
  - transcript repository not initialized
  - upload service not initialized
- `500 Internal Server Error`
  - unexpected retrieval failures
  - summarization failures
  - persistence/indexing failures
  - answer generation failures

## Manual Test Commands

### Health

```bash
curl -sS http://localhost:8083/api/health
```

### Upload a transcript

```bash
curl -X POST http://localhost:8083/api/transcripts/upload \
  -F "file=@tests/test_data/sample_small.srt"
```

### List uploaded transcripts

```bash
curl -sS http://localhost:8083/api/transcripts
```

### Fetch one stored summary

```bash
curl -sS http://localhost:8083/api/transcripts/sample_small_20260321_233803/summary
```

### Fetch one stored transcript

```bash
curl -sS http://localhost:8083/api/transcripts/sample_small_20260321_233803/content
```

### Keyword search

```bash
curl -X POST http://localhost:8083/api/search \
  -H "Content-Type: application/json" \
  -d '{"query": "Samsung", "top_k": 5}'
```

### Keyword search with filters

```bash
curl -X POST http://localhost:8083/api/search \
  -H "Content-Type: application/json" \
  -d '{"query": "AI", "date": "last week", "speaker": "Host"}'
```

### Stateless query

```bash
curl -X POST http://localhost:8083/api/query \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What hobbies are mentioned in this transcript?",
    "transcript_filter": "sample_small_20260321_233803",
    "include_sources": true
  }'
```

### Chat turn 1

```bash
curl -X POST http://localhost:8083/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "smoke-session-1",
    "message": "What hobbies are mentioned?",
    "transcript_filter": "sample_small_20260321_233803",
    "include_sources": true
  }'
```

### Chat follow-up turn

```bash
curl -X POST http://localhost:8083/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "smoke-session-1",
    "message": "Tell me more about them.",
    "transcript_filter": "sample_small_20260321_233803",
    "include_sources": true
  }'
```

### Streaming chat

```bash
curl -N -X POST http://localhost:8083/api/chat/stream \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "session_id": "smoke-session-stream-1",
    "message": "Summarize the main points.",
    "transcript_filter": "sample_small_20260321_233803",
    "include_sources": false
  }'
```

### Bad upload example

```bash
curl -X POST http://localhost:8083/api/transcripts/upload \
  -F "file=@notes.txt"
```

Expected response:

```json
{
  "detail": "Only .srt files are supported"
}
```

## Known Behavior / Caveats

- Querying with an unknown `transcript_filter` currently returns `200` with an empty-source answer rather than an explicit validation error.
- Reranker availability does not block startup; the API degrades if it is unavailable.
- BM25 and phonetic retrieval availability depend on whether uploaded content has been indexed already.
- Fuzzy matching may be unavailable if the optional dependency is not installed.
- Session storage is in-memory only; sessions are lost when the server restarts.
