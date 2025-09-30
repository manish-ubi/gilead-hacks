### Codebase flow (end-to-end)

- Ingest and index
  - Local PDFs → S3:
    - `src/sync_local_to_s3.py` uploads a folder to S3 prefix.
  - Text extraction (Textract):
    - `src/ingest_textract.py` starts/monitors Textract per PDF, writes `processed/*.txt` back to S3.
  - Knowledge Base sync:
    - `src/kb_sync.py` triggers Bedrock KB ingestion job for the S3 data source.
  - Orchestrated pipeline:
    - `src/pipeline_run.py` runs: upload (optional) → Textract → KB sync in one go.

- Query path (RAG via Bedrock Agent)
  - Request entry:
    - `src/lambda_handler.py` receives a query (from local run, Streamlit, or API).
  - Caching:
    - Computes `query_hash` (`hash_query` in `src/aws_helpers.py`).
    - Reads/writes DynamoDB cache via `src/cache_dynamodb.py`.
  - Agent invocation:
    - Calls `invoke_agent(...)` in `src/aws_helpers.py` (Bedrock Agent Runtime stream).
    - Agent uses the attached KB to retrieve relevant chunks and generates an answer.
  - Response:
    - Returns final answer; caches it with TTL.

- UI
  - `streamlit_app.py`:
    - Local mode: directly calls `lambda_handler.handler`.
    - Remote mode: calls API Gateway `/ask` if you deploy Lambda with SAM.

- Shared AWS utilities
  - `src/aws_helpers.py`:
    - Region-aware boto3 session and clients
    - S3 helpers (`s3_list`, `s3_put_text`)
    - Bedrock Agent invocation (`invoke_agent`)
    - KB ingestion trigger (`start_kb_sync`)
    - Query hashing (`hash_query`)
  - `src/logging_utils.py`:
    - Colored logger used across all modules.

### Typical runtime sequence

1) Data prep
- `python src/pipeline_run.py --dir "<local-pdf-dir>" --bucket "<bucket>" --kb-id "<KB_ID>" --ds-id "<DATA_SOURCE_ID>" --pdf-prefix "raw/" --processed-prefix "processed/"`
  - Uploads local PDFs → Textract to `processed/` → KB sync.

2) Ask a question
- `export BEDROCK_AGENT_ID=<...>; export BEDROCK_AGENT_ALIAS_ID=<...>`
- `python -m src.lambda_handler "Your question"`
  - Checks cache → invokes Agent → returns grounded answer → stores in cache.

3) Optional UI
- `streamlit run streamlit_app.py`
  - Toggle OFF to use local handler; ON with `API_URL` if deployed.

### Key files and their roles

- `src/sync_local_to_s3.py`: Upload local PDFs to S3.
- `src/ingest_textract.py`: Textract text extraction to `processed/`.
- `src/kb_sync.py`: Trigger KB ingestion (re-index).
- `src/pipeline_run.py`: One-command pipeline (upload → extract → KB sync).
- `src/lambda_handler.py`: Handles queries, cache, Agent invoke, response.
- `src/cache_dynamodb.py`: DynamoDB cache (get/put with TTL).
- `src/aws_helpers.py`: AWS clients, S3 ops, Agent invoke, KB sync, hashing.
- `streamlit_app.py`: Minimal UI.
- `template.yaml`: SAM deploy for Lambda + API + DDB.
- `INGESTION_GUIDE.md`: Step-by-step ingestion/indexing guide.