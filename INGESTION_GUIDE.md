# Ingestion & Indexing Guide (Local Folder or Existing S3 PDFs)

This guide shows two ways to prepare documents for your Bedrock Knowledge Base:
- A) From a local folder of PDFs (code-only)
- B) From PDFs already uploaded via S3 Console (UI)

It also covers syncing the Knowledge Base and asking questions via Lambda/Streamlit.

## Prerequisites
- Region enabled for Bedrock, Textract (e.g., us-west-2)
- AWS credentials configured (SSO or access keys)
- Python venv set up and requirements installed

```bash
cd gilead-hacks/agentic-qa-aws
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export AWS_REGION=us-west-2
export AWS_DEFAULT_REGION=us-west-2
```

## A) Ingest from Local Folder (code-only, no AWS UI)

1. Upload local PDFs to S3 under a prefix (e.g., raw/):
```bash
export LOCAL_PDF_DIR="/path/to/local/pdfs"
export S3_BUCKET="<your-bucket>"           # e.g., gilead-hacks
python src/sync_local_to_s3.py --dir "$LOCAL_PDF_DIR" --bucket "$S3_BUCKET" --prefix "raw/"
```

2. Run the end-to-end pipeline (sync -> Textract -> KB sync):
- You need your KB ID and Data Source ID (see “Finding KB IDs” below)
```bash
export KB_ID="<your-kb-id>"
export DATA_SOURCE_ID="<your-data-source-id>"
python src/pipeline_run.py --dir "$LOCAL_PDF_DIR" \
  --bucket "$S3_BUCKET" \
  --kb-id "$KB_ID" --ds-id "$DATA_SOURCE_ID" \
  --pdf-prefix "raw/" --processed-prefix "processed/"
```
What it does:
- Uploads local PDFs (if not already uploaded)
- Runs Textract on each PDF and writes plain text to `s3://$S3_BUCKET/processed/*.txt`
- Triggers KB ingestion so the KB indexes the new content

## B) Ingest from PDFs already in S3 (uploaded via UI)

If you already uploaded PDFs to `s3://<bucket>/data/` using the S3 Console:

1. Run the pipeline pointing to that prefix (no local upload needed):
```bash
export S3_BUCKET="gilead-hacks"      # example bucket
export KB_ID="<your-kb-id>"
export DATA_SOURCE_ID="<your-data-source-id>"
python src/pipeline_run.py --dir "/tmp/empty" \
  --bucket "$S3_BUCKET" \
  --kb-id "$KB_ID" --ds-id "$DATA_SOURCE_ID" \
  --pdf-prefix "data/" --processed-prefix "processed/"
```
What it does:
- Finds PDFs under `s3://$S3_BUCKET/data/`
- Runs Textract and writes to `processed/`
- Syncs the KB

## Finding Knowledge Base (KB) and Data Source IDs

Console:
- Bedrock → Knowledge bases → select your KB → Overview → "Knowledge base ID"
- Bedrock → Knowledge bases → select KB → Data sources → select your S3 data source → "Data source ID"

CLI:
```bash
aws bedrock-agent list-knowledge-bases --region $AWS_REGION \
  --query "knowledgeBaseSummaries[].{Name:name,Id:knowledgeBaseId}"
aws bedrock-agent list-data-sources --region $AWS_REGION --knowledge-base-id "$KB_ID" \
  --query "dataSourceSummaries[].{Name:name,Id:dataSourceId}"
```

## Ask Questions (no API required)

Set Agent env and run locally:
```bash
export BEDROCK_AGENT_ID="<Agent ID>"
export BEDROCK_AGENT_ALIAS_ID="<Alias ID>"
python -m src.lambda_handler "What is SPEC-M0778 about?"
```

Streamlit (local):
```bash
streamlit run streamlit_app.py
# leave the toggle OFF (uses local handler)
```

## Notes & Troubleshooting
- Colored logs are enabled; set `LOG_LEVEL=DEBUG` for more detail.
- Region must match where KB/Agent exist.
- If DynamoDB cache is not set, the app still works (cache fails open).
- To include citations, add to Agent instructions: "Include document identifiers and page/snippet refs for every claim."
