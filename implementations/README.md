# RAG Q&A System for Transcripts

A route-aware Retrieval-Augmented Generation (RAG) system for transcript QA. It combines vector search, BM25, phonetic search, fuzzy matching, transcript summaries, and large-context prompt assembly so specific questions stay precise while vague transcript-wide questions get broader evidence coverage.

## Project Structure

The codebase is organized as follows:

- **`src/`**: Shared source code and core components.
  - `rag_initializer.py`: Central initialization logic.
  - `rag_retriever.py`: Hybrid retrieval logic.
  - `route_aware_context.py`: Route-specific retrieval profiles and token-budgeted context packing.
  - `chatbot.py`: CLI chatbot implementation.
  - `api.py`: FastAPI application.
  - `rag_config.py`: Configuration constants.
  - `summarize_transcript.py`: Hierarchical transcript summarization pipeline.
- **`evaluation/`**: Scripts for evaluating RAG performance.
  - `evaluate_rag.py`: Main evaluation script (Hit Rate, MRR, Accuracy, route breakdown, ablations).
  - `evaluate_speed.py`: Speed benchmarking.
  - `evaluate_vague_rag.py`: End-to-end evaluation on vague/global questions.
  - `visualizer.py`: Plot generation.
- **`generation/`**: Tools for generating ground truth data.
  - `generate_ground_truth.py`: Generate Q&A pairs from transcripts.
- **`tuning/`**: Hyperparameter tuning scripts.
  - `tune_top_k.py`: Optimize `k` retrieval parameters.
  - `tune_weights.py`: Optimize ensemble weights.
- **`scripts/`**: Utility scripts.
  - `build_global_index.py`: Build/Rebuild the global vector store.
  - `check_progress.py`: Monitor tuning progress.
- **`transcripts/`**: Directory for `.srt` files (input data).
- **`vector_stores/`**: Persisted ChromaDB and indices.

## Prerequisites

1. **Python 3.10+**
2. **External Services**:
   - Embedding Service: Running on `localhost:8081`
   - Reranker Service: Running on `localhost:8082` (optional but recommended)
   - LLM Service/API: DeepSeek API or local LLM on `localhost:8080` (if using local mode)
3. **DeepSeek API Key**:
   ```bash
   export DEEPSEEK_API_KEY="your_api_key_here"
   ```

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
   *(Note: Ensure `requirements.txt` is updated with necessary packages)*

2. Start external services (Embeddings, Reranker).

## Quick Start

### 1. Build the Index
Before running queries, build the search index from your transcripts:
```bash
python3 scripts/build_global_index.py --force-rebuild
```

### 2. Run the API Server
Start the FastAPI backend (available at `localhost:8083`):
```bash
python3 run_api.py
```
Access documentation at [http://localhost:8083/docs](http://localhost:8083/docs).

### 3. Run CLI Chatbot
For testing in the terminal:
```bash
python3 src/chatbot.py
```

## Pipelines & Workflows

### Generating Ground Truth
To evaluate the system, first generate Q&A pairs from your transcripts:
```bash
python3 generation/generate_ground_truth.py --all
```
This generates JSON files in `ground_truths/`.

### Evaluation
Run a full evaluation on the generated ground truths:
```bash
python3 evaluation/evaluate_rag.py --all
```
Results are saved to timestamped folders in `evaluations/`.

Run vague/global evaluation:
```bash
python3 evaluation/evaluate_vague_rag.py --all
```

Run an ablation preset for route-aware large-context behavior:
```bash
python3 evaluation/evaluate_rag.py --all --ablation full_with_neighbors
```

To evaluate retrieval speed and compare with Pure LLM:
```bash
python3 evaluation/evaluate_speed.py
```

### Hyperparameter Tuning
Optimize the RAG pipeline parameters:

1. **Tune Top-K**:
   ```bash
   python3 tuning/tune_top_k.py
   ```
2. **Tune Ensemble Weights** (after Top-K):
   ```bash
   python3 tuning/tune_weights.py
   ```

## Testing
Run the test suite using `pytest`:
```bash
pytest tests/
```

## configuration
Adjust core settings in `src/rag_config.py`:
- `RERANKER_ENABLED`: Enable/Disable reranking.
- `PHONETIC_ENABLED`: Enable/Disable phonetic search.
- `ANSWER_MODEL`: Answer generation backend (`local` or `deepseek`).
- `ROUTE_CONTEXT_TOKEN_BUDGETS`: Per-route prompt budgets for large-context packing.
- `ROUTE_RETRIEVAL_PROFILES`: Per-route retrieval depth, rerank depth, and neighbor settings.
- `ROUTE_SUPPORTING_LIMITS`: Max supporting chunks retained per route before token packing.
- `ROUTE_FRAME_LIMITS`: Anchor chunk counts for opening, early, middle, late, and closing transcript sections.
