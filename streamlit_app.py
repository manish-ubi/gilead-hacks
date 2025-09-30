import json
import os
import pathlib
from typing import List
import streamlit as st

from src.lambda_handler import handler as local_handler
from src.logging_utils import GREEN, RED, BLUE
from src.pipeline_run import run_pipeline
from src.sync_local_to_s3 import upload_pdfs
from src.aws_helpers import kendra_query

st.set_page_config(page_title="Gilead QA (AWS)", layout="wide")

# Sidebar: Environment and configuration
st.sidebar.header("Configuration")
aws_region = st.sidebar.text_input("AWS Region", value=os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "ap-south-1")))
agent_id = st.sidebar.text_input("Bedrock Agent ID", value=os.getenv("BEDROCK_AGENT_ID", "HMEOFY61M0"))
agent_alias_id = st.sidebar.text_input("Bedrock Agent Alias ID", value=os.getenv("BEDROCK_AGENT_ALIAS_ID", "RDQLJ8DFLH"))
bucket = st.sidebar.text_input("S3 Bucket", value=os.getenv("BUCKET", "gilead-hacks"))
kb_id = st.sidebar.text_input("Knowledge Base ID", value=os.getenv("KB_ID", "LIKLETJXU0"))
ds_id = st.sidebar.text_input("Data Source ID", value=os.getenv("DS_ID", "NQPTGDLADX"))
pdf_prefix = st.sidebar.text_input("PDF Prefix", value=os.getenv("PDF_PREFIX", "data/"))
processed_prefix = st.sidebar.text_input("Processed Prefix", value=os.getenv("PROCESSED_PREFIX", "processed/"))
kendra_index_id = st.sidebar.text_input("(Optional) Kendra Index ID for citations", value=os.getenv("KENDRA_INDEX_ID", ""))

if st.sidebar.button("Apply Environment"):
	os.environ["AWS_REGION"] = aws_region
	os.environ["BEDROCK_AGENT_ID"] = agent_id
	os.environ["BEDROCK_AGENT_ALIAS_ID"] = agent_alias_id
	os.environ["BUCKET"] = bucket
	os.environ["KB_ID"] = kb_id
	os.environ["DS_ID"] = ds_id
	os.environ["PDF_PREFIX"] = pdf_prefix
	os.environ["PROCESSED_PREFIX"] = processed_prefix
	if kendra_index_id:
		os.environ["KENDRA_INDEX_ID"] = kendra_index_id
	st.sidebar.success("Environment applied")

st.title("Gilead Agentic QA (AWS)")
tabs = st.tabs(["PDF Q&A", "CSV SQL"])

col1, col2 = st.columns(2)

with tabs[0]:
	col1, col2 = st.columns(2)

	with col1:
	st.subheader("Ingest PDFs")
	uploaded_files = st.file_uploader("Upload one or more PDFs", type=["pdf"], accept_multiple_files=True)
	ingest_dir = st.text_input("Or provide a local directory path of PDFs", value="")

	if st.button("Run Ingestion"):
		if not bucket or not kb_id or not ds_id:
			st.error("Please set Bucket, KB ID, and DS ID in the sidebar.")
			st.stop()
		with st.spinner("Ingesting..."):
			try:
				target_dir = None
				if uploaded_files:
					target_dir = pathlib.Path("uploaded").absolute()
					target_dir.mkdir(parents=True, exist_ok=True)
					written: List[str] = []
					for f in uploaded_files:
						out_path = target_dir / f.name
						with open(out_path, "wb") as w:
							w.write(f.read())
						written.append(str(out_path))
					# Upload only; pipeline will also process and sync
					upload_pdfs(str(target_dir), bucket, pdf_prefix)
					st.success(f"Uploaded {len(written)} file(s) to s3://{bucket}/{pdf_prefix}")
					ingest_dir = str(target_dir)
				if ingest_dir:
					run_pipeline(ingest_dir, bucket, kb_id, ds_id, pdf_prefix, processed_prefix)
					st.success("Pipeline completed (upload/textract/kb sync)")
				else:
					st.warning("Please upload PDFs or provide a directory path.")
			except Exception as e:
				st.error(f"Ingestion failed: {e}")

	with col2:
	st.subheader("Ask the Agent")
	query = st.text_input("Enter your question:")
	use_remote = st.toggle("Use remote API (API Gateway)", value=False)
	api_url = st.text_input("API URL", value=os.getenv("API_URL", "")) if use_remote else None

	if st.button("Ask"):
		if not query.strip():
			st.warning("Please enter a question.")
			st.stop()
		with st.spinner("Thinking..."):
			try:
				if use_remote and api_url:
					import requests
					resp = requests.post(api_url, json={"query": query}, timeout=60)
					if resp.status_code != 200:
						st.error(f"Error: {resp.status_code} {resp.text}")
						st.stop()
					data = resp.json()
					st.markdown(f"{BLUE}Remote API call succeeded{BLUE}")
				else:
					resp = local_handler({"query": query}, None)
					data = json.loads(resp["body"]) if isinstance(resp, dict) else resp
					st.markdown(f"{GREEN}Local handler call succeeded{GREEN}")
				st.subheader("Answer")
				st.write(data.get("answer", "No answer"))
				# Optional citations via Kendra
				if kendra_index_id:
					st.caption("Citations (from Kendra)")
					try:
						results = kendra_query(kendra_index_id, query, top_k=3)
						for r in results:
							st.markdown(f"- {r.get('DocumentId', 'doc')}\n\n> {r.get('Text', '')}")
					except Exception as ke:
						st.info(f"Citations unavailable: {ke}")
			except Exception as e:
				st.markdown(f"{RED}Error: {e}{RED}")

with tabs[1]:
	st.subheader("CSV Workspace (DuckDB)")
	import duckdb
	workspace = pathlib.Path("csv_workspace").absolute()
	workspace.mkdir(parents=True, exist_ok=True)
	db_path = workspace / "workspace.duckdb"
	conn = duckdb.connect(str(db_path))

	csvs = st.file_uploader("Upload CSV files", type=["csv"], accept_multiple_files=True)
	if csvs and st.button("Load CSVs"):
		loaded: List[str] = []
		for f in csvs:
			csv_path = workspace / f.name
			with open(csv_path, "wb") as w:
				w.write(f.read())
			# Create or replace table named from file (sans extension)
			table = f.name.rsplit(".", 1)[0]
			conn.execute(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM read_csv_auto(?)", [str(csv_path)])
			loaded.append(table)
		st.success(f"Loaded tables: {', '.join(loaded)}")

	st.caption("Run SQL against your loaded tables")
	sql = st.text_area("SQL", value="SELECT * FROM information_schema.tables LIMIT 20;", height=140)
	gen_from_nl = st.text_input("Or describe what you want (NL → SQL)")
	if st.button("Generate SQL from NL") and gen_from_nl.strip():
		from src.aws_helpers import invoke_bedrock
		prompt = [
			{"role": "user", "content": f"You are a SQL assistant for DuckDB. Based on the user's request, write a single DuckDB SQL statement. Only output SQL. Request: {gen_from_nl}"}
		]
		try:
			proposed = invoke_bedrock(prompt, model_id=os.getenv("BEDROCK_MODEL_ID"))
			st.code(proposed.strip(), language="sql")
			if st.toggle("Run generated SQL", value=False):
				try:
					res = conn.execute(proposed).df()
					st.dataframe(res)
				except Exception as qe:
					st.error(f"Query failed: {qe}")
		except Exception as e:
			st.error(f"Generation failed: {e}")

	if st.button("Run SQL") and sql.strip():
		try:
			res = conn.execute(sql).df()
			st.dataframe(res)
		except Exception as e:
			st.error(f"SQL error: {e}")
