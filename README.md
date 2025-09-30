# Gilead Agentic QA on AWS (Bedrock KB + Agents)

This project implements an AWS-native QA system using S3, Textract, Bedrock Knowledge Bases (embeddings + retrieval), Bedrock Agents (RAG orchestration), Bedrock Guardrails (optional), DynamoDB cache, Lambda API, and a minimal Streamlit UI.

## Prereqs
- AWS account with access to Bedrock (Agents, KB), Textract, DynamoDB, Lambda, API Gateway
- Enable Bedrock access in your region (e.g., us-west-2)
- Python 3.10+

## Install
```bash
cd gilead-hacks/agentic-qa-aws
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Environment
Required:
- AWS_REGION (e.g., us-west-2)
- S3_BUCKET=pd m-pdm-dl-quality-docs-genai-dev.gvault_test
- BEDROCK_MODEL_ID=anthropic.claude-3-sonnet-20240229-v1:0 (used by Agent/KB where applicable)
- BEDROCK_AGENT_ID=<your-agent-id>
- BEDROCK_AGENT_ALIAS_ID=<your-agent-alias-id>
- DDB_TABLE=agentic_qa_cache

Optional:
- MAX_TOKENS=400
- API_URL=<api-gateway-endpoint>

## Step 1 – Ingest with Textract
Upload PDFs to S3, then extract text to `processed/`:
```bash
python src/ingest_textract.py --bucket "$S3_BUCKET" --keys \
  "SPEC-M0778" \
  "REP-48893" \
  "REP-63010 2025 Annual Quality Review DESCOVY® emtricitabine 200 mg / tenofovir alafenamide 10 mg.pdf"
```

## Step 2 – Bedrock Knowledge Base
Create a Knowledge Base (KB) in the console:
- Data source: S3 pointing to `s3://$S3_BUCKET/processed/`
- Embeddings: Amazon Titan Embeddings G1
- Chunking: automatic (e.g., 500–1000 tokens)
- After creation, note KB ID and Data Source ID
- To sync after new docs are added:
```bash
python src/kb_sync.py --kb-id <KB_ID> --ds-id <DATA_SOURCE_ID>
```

## Step 3 – Bedrock Agent
Create an Agent in the console:
- Attach the Knowledge Base
- Model: Claude 3 Sonnet (or similar)
- Instructions: answer only from KB; if not found, say "Sorry, this information is not available in the documents."
- Create an Alias; note Agent ID and Alias ID

## Run locally (no deploy)
```bash
export AWS_REGION=us-west-2
export S3_BUCKET="pdm-pdm-dl-quality-docs-genai-dev.gvault_test"
export DDB_TABLE="agentic_qa_cache"
export BEDROCK_AGENT_ID="<agent-id>"
export BEDROCK_AGENT_ALIAS_ID="<alias-id>"
python -m src.lambda_handler "What is SPEC-M0778 about?"
```

## Streamlit UI
```bash
streamlit run streamlit_app.py
```

## Deploy (SAM)
```bash
sam build
sam deploy --guided
# provide: DynamoTableName, BedrockAgentId, BedrockAgentAliasId
```

## Notes
- Guardrails can be attached to the Agent in console for safety.
- The Lambda uses DynamoDB to cache answers by `query_hash` with TTL.
