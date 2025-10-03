import json
import os
import pathlib
import time
from typing import List, Dict, Any, Optional
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from src.lambda_handler import handler as local_handler
from src.logging_utils import GREEN, RED, BLUE, pipeline_logger
from src.pipeline_run import run_pipeline
from src.sync_local_to_s3 import upload_pdfs
from src.aws_helpers import kendra_query, hash_query
from src.csv_sql_handler import CSVSqlHandler
from src.feedback_system import FeedbackSystem
from src.cache_dynamodb import get_cache_stats, invalidate_cache, cleanup_expired_cache

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

# Initialize session state
if "csv_handler" not in st.session_state:
	st.session_state.csv_handler = None
if "feedback_system" not in st.session_state:
	st.session_state.feedback_system = FeedbackSystem()
if "query_history" not in st.session_state:
	st.session_state.query_history = []
if "feedback_history" not in st.session_state:
	st.session_state.feedback_history = {}
if "generated_sql" not in st.session_state:
	st.session_state.generated_sql = None
if "generated_sql_valid" not in st.session_state:
	st.session_state.generated_sql_valid = False

st.title("Gilead Agentic QA (AWS) - Enhanced")
tabs = st.tabs(["📄 PDF Q&A", "📊 CSV SQL", "📈 Analytics", "⚙️ Cache Management"])

# PDF Q&A Tab
with tabs[0]:
	st.header("📄 PDF Document Q&A")
	
	# Mode selection
	mode = st.radio("Select Mode:", ["Index New Documents", "Query Existing Documents"], horizontal=True)
	
	if mode == "Index New Documents":
		st.subheader("📤 Ingest PDFs")
		col1, col2 = st.columns(2)
		
		with col1:
			uploaded_files = st.file_uploader("Upload one or more PDFs", type=["pdf"], accept_multiple_files=True)
			ingest_dir = st.text_input("Or provide a local directory path of PDFs", value="")
		
		with col2:
			st.info("**Indexing Process:**\n1. Upload PDFs to S3\n2. Extract text with Textract\n3. Sync with Knowledge Base\n4. Ready for querying")
		
		if st.button("🚀 Run Ingestion", type="primary"):
			if not bucket or not kb_id or not ds_id:
				st.error("Please set Bucket, KB ID, and DS ID in the sidebar.")
				st.stop()
			
			operation_id = pipeline_logger.start_operation("PDF_INGESTION")
			
			with st.spinner("Ingesting documents..."):
				try:
					target_dir = None
					file_types = {}
					total_size = 0
					written = []
					
					if uploaded_files:
						target_dir = pathlib.Path("uploaded").absolute()
						target_dir.mkdir(parents=True, exist_ok=True)
						
						for f in uploaded_files:
							out_path = target_dir / f.name
							with open(out_path, "wb") as w:
								w.write(f.read())
							written.append(str(out_path))
							file_ext = f.name.split('.')[-1]
							file_types[file_ext] = file_types.get(file_ext, 0) + 1
							total_size += f.size
						
						# Upload to S3
						upload_pdfs(str(target_dir), bucket, pdf_prefix)
						pipeline_logger.log_step("S3 upload completed")
						st.success(f"Uploaded {len(written)} file(s) to s3://{bucket}/{pdf_prefix}")
						ingest_dir = str(target_dir)
					
					if ingest_dir:
						# Run full pipeline
						run_pipeline(ingest_dir, bucket, kb_id, ds_id, pdf_prefix, processed_prefix)
						pipeline_logger.log_indexing(len(written) if uploaded_files else 0, total_size, file_types)
						pipeline_logger.end_operation(True)
						st.success("✅ Pipeline completed (upload/textract/kb sync)")
					else:
						st.warning("Please upload PDFs or provide a directory path.")
						
				except Exception as e:
					pipeline_logger.end_operation(False, str(e))
					st.error(f"❌ Ingestion failed: {e}")
	
	else:  # Query Existing Documents
		st.subheader("❓ Ask the Agent")
		col1, col2 = st.columns([2, 1])
		
		with col1:
			query = st.text_input("Enter your question:", placeholder="What is SPEC-M0778 about?")
			use_remote = st.toggle("Use remote API (API Gateway)", value=False)
			api_url = st.text_input("API URL", value=os.getenv("API_URL", "")) if use_remote else None
		
		with col2:
			st.metric("Cache Status", "Active" if os.getenv("DDB_TABLE") else "Disabled")
			if st.button("🧹 Clean Cache"):
				with st.spinner("Cleaning cache..."):
					cleaned = cleanup_expired_cache()
					st.success(f"Cleaned {cleaned} expired entries")
		
		if st.button("🔍 Ask Question", type="primary"):
			if not query.strip():
				st.warning("Please enter a question.")
				st.stop()
			
			operation_id = pipeline_logger.start_operation("QUERY_PROCESSING")
			start_time = time.time()
			
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
					
					response_time = time.time() - start_time
					answer = data.get("answer", "No answer")
					cached = data.get("cached", False)
					
					pipeline_logger.log_query(query, len(answer), cached, response_time)
					pipeline_logger.end_operation(True)
					
					# Display answer
					st.subheader("💬 Answer")
					st.write(answer)
					
					# Feedback system
					query_hash = hash_query(query)
					col_like, col_dislike = st.columns(2)
					
					with col_like:
						if st.button("👍 Like", key=f"like_{query_hash}"):
							success = st.session_state.feedback_system.record_feedback(
								query_hash, query, answer, "positive"
							)
							if success:
								st.success("✅ Feedback recorded!")
								st.session_state.feedback_history[query_hash] = "positive"
							else:
								st.error("❌ Failed to record feedback")
					
					with col_dislike:
						if st.button("👎 Dislike", key=f"dislike_{query_hash}"):
							success = st.session_state.feedback_system.record_feedback(
								query_hash, query, answer, "negative"
							)
							if success:
								st.success("✅ Feedback recorded!")
								st.session_state.feedback_history[query_hash] = "negative"
							else:
								st.error("❌ Failed to record feedback")
					
					# Show feedback status
					if query_hash in st.session_state.feedback_history:
						feedback_type = st.session_state.feedback_history[query_hash]
						emoji = "👍" if feedback_type == "positive" else "👎"
						st.info(f"{emoji} You {feedback_type} this response")
					
					# Store in query history
					st.session_state.query_history.append({
						"query": query,
						"answer": answer,
						"cached": cached,
						"response_time": response_time,
						"timestamp": time.time()
					})
					
					# Citations
					if kendra_index_id:
						st.caption("📚 Citations (from Kendra)")
						try:
							results = kendra_query(kendra_index_id, query, top_k=3)
							for r in results:
								st.markdown(f"- {r.get('DocumentId', 'doc')}\n\n> {r.get('Text', '')}")
						except Exception as ke:
							st.info(f"Citations unavailable: {ke}")
							
				except Exception as e:
					pipeline_logger.end_operation(False, str(e))
					st.markdown(f"{RED}Error: {e}{RED}")

# CSV SQL Tab
with tabs[1]:
	st.header("📊 CSV Data Analysis with Natural Language")
	
	# Initialize CSV handler
	if st.session_state.csv_handler is None:
		st.session_state.csv_handler = CSVSqlHandler()
	
	csv_handler = st.session_state.csv_handler
	
	# File upload section
	st.subheader("📁 Load CSV Files")
	csv_files = st.file_uploader("Upload CSV files", type=["csv"], accept_multiple_files=True)
	
	if csv_files and st.button("📥 Load CSVs", type="primary"):
		operation_id = pipeline_logger.start_operation("CSV_LOADING")
		
		# Save uploaded files
		workspace = pathlib.Path("csv_workspace").absolute()
		workspace.mkdir(parents=True, exist_ok=True)
		
		file_paths = []
		for f in csv_files:
			csv_path = workspace / f.name
			with open(csv_path, "wb") as w:
				w.write(f.read())
			file_paths.append(str(csv_path))
		
		# Load into database
		with st.spinner("Loading CSV files..."):
			try:
				result = csv_handler.load_csv_files(file_paths)
				pipeline_logger.log_csv_loading(
					len(csv_files), 
					result["success_count"], 
					result["error_count"]
				)
				pipeline_logger.end_operation(True)
				
				if result["success_count"] > 0:
					st.success(f"✅ Loaded {result['success_count']} tables successfully!")
					for table in result["loaded_tables"]:
						st.info(f"📊 {table['table_name']}: {table['row_count']} rows, {len(table['columns'])} columns")
				
				if result["errors"]:
					st.warning(f"⚠️ {len(result['errors'])} errors occurred")
					for error in result["errors"]:
						st.error(error)
						
			except Exception as e:
				pipeline_logger.end_operation(False, str(e))
				st.error(f"❌ Loading failed: {e}")
	
	# Show loaded tables
	tables = csv_handler.get_all_tables()
	if tables:
		st.subheader("📋 Loaded Tables")
		for table in tables:
			with st.expander(f"📊 {table['table_name']} ({table['row_count']} rows)"):
				col1, col2 = st.columns(2)
				with col1:
					st.write("**Columns:**")
					for col in table['columns']:
						st.write(f"- {col['name']} ({col['type']})")
				with col2:
					# Show sample data
					sample = csv_handler.get_table_sample(table['table_name'])
					if sample is not None:
						st.write("**Sample Data:**")
						st.dataframe(sample, use_container_width=True)
	
	# Natural Language to SQL
	st.subheader("🤖 Natural Language to SQL")
	col1, col2 = st.columns([2, 1])
	
	with col1:
		nl_question = st.text_input(
			"Ask a question about your data:", 
			placeholder="What are the top 5 products by sales?"
		)
	
	with col2:
		selected_table = st.selectbox(
			"Focus on table (optional):", 
			["All tables"] + [t['table_name'] for t in tables]
		) if tables else None
	
	if st.button("🔍 Generate SQL", type="primary") and nl_question.strip():
		operation_id = pipeline_logger.start_operation("SQL_GENERATION")
		
		with st.spinner("Generating SQL..."):
			try:
				table_context = selected_table if selected_table != "All tables" else None
				sql_query = csv_handler.natural_language_to_sql(nl_question, table_context)
				
				st.subheader("📝 Generated SQL")
				st.code(sql_query, language="sql")
				# Persist generated SQL
				st.session_state.generated_sql = sql_query
				
				# Validate SQL
				is_valid, error_msg = csv_handler.validate_sql(sql_query)
				if is_valid:
					st.success("✅ SQL is valid and safe")
					st.session_state.generated_sql_valid = True
					pipeline_logger.log_sql_generation(nl_question, sql_query, True)
					
					# Execute button (uses stored SQL)
					if st.button("▶️ Execute SQL", type="primary", key="execute_generated_sql"):
						with st.spinner("Executing query..."):
							success, df, error_msg = csv_handler.execute_sql(st.session_state.generated_sql)
							if success:
								st.subheader("📊 Results")
								st.dataframe(df, use_container_width=True)
								# Show summary stats
								if len(df) > 0:
									st.info(f"📈 Returned {len(df)} rows, {len(df.columns)} columns")
							else:
								st.error(f"❌ Execution failed: {error_msg}")
				else:
					st.error(f"❌ SQL validation failed: {error_msg}")
					st.session_state.generated_sql_valid = False
					pipeline_logger.log_sql_generation(nl_question, sql_query, False)
				
				pipeline_logger.end_operation(True)
				
			except Exception as e:
				pipeline_logger.end_operation(False, str(e))
				st.error(f"❌ Generation failed: {e}")
	
	# Manual SQL execution
	st.subheader("✏️ Manual SQL Execution")
	manual_sql = st.text_area(
		"Write your SQL query:", 
		value="SELECT * FROM information_schema.tables LIMIT 10;",
		height=100
	)
	
	if st.button("▶️ Execute Manual SQL", type="secondary", key="execute_manual_sql") and manual_sql.strip():
		with st.spinner("Executing..."):
			success, df, error_msg = csv_handler.execute_sql(manual_sql)
			if success:
				st.dataframe(df, use_container_width=True)
			else:
				st.error(f"❌ {error_msg}")

# Analytics Tab
with tabs[2]:
	st.header("📈 Analytics & Insights")
	
	# Cache statistics
	st.subheader("💾 Cache Statistics")
	cache_stats = get_cache_stats()
	if "error" not in cache_stats:
		col1, col2, col3, col4 = st.columns(4)
		with col1:
			st.metric("Total Entries", cache_stats.get("total_entries", 0))
		with col2:
			st.metric("Avg Access Count", f"{cache_stats.get('avg_access_count', 0):.1f}")
		with col3:
			st.metric("Max Access Count", cache_stats.get("max_access_count", 0))
		with col4:
			age = cache_stats.get("oldest_entry_age_hours", 0)
			st.metric("Oldest Entry (hrs)", f"{age:.1f}" if age else "N/A")
	else:
		st.warning("Cache statistics unavailable")
	
	# Feedback statistics
	st.subheader("👍👎 Feedback Statistics")
	feedback_stats = st.session_state.feedback_system.get_feedback_stats()
	if "error" not in feedback_stats:
		col1, col2, col3 = st.columns(3)
		with col1:
			st.metric("Total Feedback", feedback_stats.get("total_feedback", 0))
		with col2:
			positive_ratio = feedback_stats.get("positive_ratio", 0)
			st.metric("Positive Ratio", f"{positive_ratio:.1%}")
		with col3:
			negative_ratio = feedback_stats.get("negative_ratio", 0)
			st.metric("Negative Ratio", f"{negative_ratio:.1%}")
		
		# Feedback visualization
		if feedback_stats.get("total_feedback", 0) > 0:
			fig = go.Figure(data=[
				go.Bar(name="Positive", x=["Feedback"], y=[feedback_stats.get("positive_count", 0)]),
				go.Bar(name="Negative", x=["Feedback"], y=[feedback_stats.get("negative_count", 0)])
			])
			fig.update_layout(title="Feedback Distribution", barmode="stack")
			st.plotly_chart(fig, use_container_width=True)
	else:
		st.warning("Feedback statistics unavailable")
	
	# Query history
	if st.session_state.query_history:
		st.subheader("📊 Query History")
		history_df = pd.DataFrame(st.session_state.query_history)
		
		# Response time chart
		fig = px.line(history_df, x=range(len(history_df)), y="response_time", 
					 title="Response Time Over Time")
		fig.update_xaxes(title="Query Number")
		fig.update_yaxes(title="Response Time (seconds)")
		st.plotly_chart(fig, use_container_width=True)
		
		# Cache hit rate
		cached_count = sum(1 for q in st.session_state.query_history if q.get("cached", False))
		total_count = len(st.session_state.query_history)
		cache_hit_rate = cached_count / total_count if total_count > 0 else 0
		
		st.metric("Cache Hit Rate", f"{cache_hit_rate:.1%}")
		
		# Show recent queries
		st.subheader("🕒 Recent Queries")
		for i, query in enumerate(reversed(st.session_state.query_history[-5:])):
			with st.expander(f"Query {len(st.session_state.query_history) - i}: {query['query'][:50]}..."):
				st.write(f"**Answer:** {query['answer'][:200]}...")
				st.write(f"**Cached:** {'Yes' if query.get('cached', False) else 'No'}")
				st.write(f"**Response Time:** {query.get('response_time', 0):.2f}s")

# Cache Management Tab
with tabs[3]:
	st.header("⚙️ Cache Management")
	
	col1, col2 = st.columns(2)
	
	with col1:
		st.subheader("🧹 Cache Operations")
		
		if st.button("🗑️ Clear All Cache"):
			with st.spinner("Clearing cache..."):
				deleted = invalidate_cache()
				st.success(f"✅ Deleted {deleted} cache entries")
		
		if st.button("🧽 Clean Expired Entries"):
			with st.spinner("Cleaning..."):
				cleaned = cleanup_expired_cache()
				st.success(f"✅ Cleaned {cleaned} expired entries")
		
		pattern = st.text_input("Clear by pattern (optional):", placeholder="Enter pattern to match")
		if st.button("🎯 Clear by Pattern") and pattern:
			with st.spinner("Clearing by pattern..."):
				deleted = invalidate_cache(pattern=pattern)
				st.success(f"✅ Deleted {deleted} entries matching pattern")
	
	with col2:
		st.subheader("📊 Cache Details")
		cache_stats = get_cache_stats()
		if "error" not in cache_stats:
			st.json(cache_stats)
		else:
			st.error("Cache details unavailable")
	
	# Feedback management
	st.subheader("👍👎 Feedback Management")
	recent_feedback = st.session_state.feedback_system.get_recent_feedback(limit=10)
	
	if recent_feedback:
		st.write("**Recent Feedback:**")
		for feedback in recent_feedback:
			feedback_type = feedback.get("feedback_type", "unknown")
			emoji = "👍" if feedback_type == "positive" else "👎"
			query = feedback.get("query", "")[:50]
			timestamp = feedback.get("created_at", "")
			st.write(f"{emoji} {query}... ({timestamp})")
	else:
		st.info("No recent feedback available")
	
	if st.button("🧹 Clean Old Feedback"):
		with st.spinner("Cleaning old feedback..."):
			cleaned = st.session_state.feedback_system.cleanup_old_feedback(days_old=30)
			st.success(f"✅ Cleaned {cleaned} old feedback entries")