import os
import time
import re
import sqlparse
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd
import duckdb
from .aws_helpers import invoke_bedrock
from .logging_utils import info, debug, warn, error


class CSVSqlHandler:
	"""Handler for CSV file loading and natural language to SQL conversion."""
	
	def __init__(self, workspace_dir: str = "csv_workspace"):
		self.workspace_dir = workspace_dir
		self.db_path = os.path.join(workspace_dir, "workspace.duckdb")
		self.conn = None
		self._ensure_workspace()
		self._connect_db()
	
	def _ensure_workspace(self):
		"""Ensure workspace directory exists."""
		os.makedirs(self.workspace_dir, exist_ok=True)
		info(f"Workspace directory: {self.workspace_dir}")
	
	def _connect_db(self):
		"""Connect to DuckDB database."""
		try:
			self.conn = duckdb.connect(self.db_path)
			info("Connected to DuckDB")
		except Exception as e:
			error_msg = str(e)
			error(f"Failed to connect to DuckDB: {error_msg}")
			# Retry briefly if it's a lock error
			if "lock on file" in error_msg.lower() or "conflicting lock" in error_msg.lower():
				for attempt in range(1, 6):
					time.sleep(0.5 * attempt)
					try:
						self.conn = duckdb.connect(self.db_path)
						info("Connected to DuckDB after retry")
						return
					except Exception as retry_err:
						if attempt == 5:
							warn(f"DuckDB lock persists after retries: {retry_err}")
							break
				# Fallback to per-process database to avoid blocking the app
			pid_db_path = os.path.join(self.workspace_dir, f"workspace_{os.getpid()}.duckdb")
			try:
				self.conn = duckdb.connect(pid_db_path)
				self.db_path = pid_db_path
				warn(f"Using fallback DuckDB path due to lock: {pid_db_path}")
			except Exception as final_err:
				error(f"Failed to connect to fallback DuckDB: {final_err}")
				raise

	def __del__(self):
		try:
			self.close()
		except Exception:
			pass
	
	def load_csv_files(self, csv_files: List[str]) -> Dict[str, Any]:
		"""
		Load CSV files into DuckDB tables.
		Returns information about loaded tables.
		"""
		loaded_tables = []
		errors = []
		
		for csv_file in csv_files:
			try:
				# Extract table name from filename
				table_name = os.path.splitext(os.path.basename(csv_file))[0]
				# Sanitize table name
				table_name = re.sub(r'[^a-zA-Z0-9_]', '_', table_name)
				if not table_name or table_name[0].isdigit():
					table_name = f"table_{table_name}"
				
				# Load CSV into DuckDB
				self.conn.execute(f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM read_csv_auto(?)", [csv_file])
				
				# Get table info
				table_info = self.get_table_info(table_name)
				loaded_tables.append({
					"table_name": table_name,
					"file_path": csv_file,
					"row_count": table_info["row_count"],
					"columns": table_info["columns"]
				})
				
				info(f"Loaded table '{table_name}' with {table_info['row_count']} rows")
				
			except Exception as e:
				error_msg = f"Failed to load {csv_file}: {e}"
				error(error_msg)
				errors.append(error_msg)
		
		return {
			"loaded_tables": loaded_tables,
			"errors": errors,
			"success_count": len(loaded_tables),
			"error_count": len(errors)
		}
	
	def get_table_info(self, table_name: str) -> Dict[str, Any]:
		"""Get information about a table."""
		try:
			# Get row count
			result = self.conn.execute(f"SELECT COUNT(*) as count FROM {table_name}").fetchone()
			row_count = result[0] if result else 0
			
			# Get column information
			result = self.conn.execute(f"DESCRIBE {table_name}").fetchall()
			columns = [{"name": row[0], "type": row[1]} for row in result]
			
			return {
				"row_count": row_count,
				"columns": columns
			}
		except Exception as e:
			warn(f"Failed to get table info for {table_name}: {e}")
			return {"row_count": 0, "columns": []}
	
	def get_all_tables(self) -> List[Dict[str, Any]]:
		"""Get information about all tables in the database."""
		try:
			result = self.conn.execute("SHOW TABLES").fetchall()
			tables = []
			for row in result:
				table_name = row[0]
				table_info = self.get_table_info(table_name)
				tables.append({
					"table_name": table_name,
					**table_info
				})
			return tables
		except Exception as e:
			warn(f"Failed to get tables: {e}")
			return []
	
	def natural_language_to_sql(self, question: str, table_context: Optional[str] = None) -> str:
		"""
		Convert natural language question to SQL query using Bedrock.
		"""
		# Get table information for context
		tables_info = self.get_all_tables()
		if not tables_info:
			raise ValueError("No tables available for querying")
		
		# Build context about available tables
		context_parts = []
		for table in tables_info:
			columns_str = ", ".join([f"{col['name']} ({col['type']})" for col in table['columns']])
			context_parts.append(f"Table '{table['table_name']}': {columns_str} ({table['row_count']} rows)")
		
		tables_context = "\n".join(context_parts)
		
		# Add specific table context if provided
		if table_context:
			tables_context = f"Focus on table: {table_context}\n\nAll tables:\n{tables_context}"
		
		prompt = [
			{
				"role": "user", 
				"content": f"""You are a SQL expert for DuckDB. Convert the user's natural language question to a valid DuckDB SQL query.

Available tables and their schemas:
{tables_context}

User question: {question}

Requirements:
1. Generate ONLY a valid DuckDB SQL query
2. Use proper table and column names as shown above
3. Include appropriate WHERE clauses, JOINs, and aggregations as needed
4. Use LIMIT clause if the result might be large
5. Do not include any explanations or markdown formatting
6. Ensure the query is safe and doesn't contain any dangerous operations

SQL Query:"""
			}
		]
		
		try:
			model_id = os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-3-sonnet-20240229-v1:0")
			sql_query = invoke_bedrock(prompt, model_id=model_id, max_tokens=500, temperature=0.1)
			
			# Clean up the response
			sql_query = sql_query.strip()
			if sql_query.startswith("```sql"):
				sql_query = sql_query[6:]
			if sql_query.endswith("```"):
				sql_query = sql_query[:-3]
			sql_query = sql_query.strip()
			
			info(f"Generated SQL: {sql_query}")
			return sql_query
			
		except Exception as e:
			error(f"Failed to generate SQL: {e}")
			raise
	
	def validate_sql(self, sql_query: str) -> Tuple[bool, Optional[str]]:
		"""
		Validate SQL query for safety and syntax.
		Returns (is_valid, error_message).
		"""
		try:
			# Parse SQL to check syntax
			parsed = sqlparse.parse(sql_query)
			if not parsed:
				return False, "Empty SQL query"
			
			# Check for dangerous operations
			dangerous_keywords = [
				"DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "CREATE", "TRUNCATE",
				"EXEC", "EXECUTE", "CALL", "GRANT", "REVOKE"
			]
			
			upper_sql = sql_query.upper()
			for keyword in dangerous_keywords:
				if keyword in upper_sql:
					return False, f"Dangerous operation detected: {keyword}"
			
			# Try to explain the query (DuckDB's EXPLAIN will validate syntax)
			try:
				self.conn.execute(f"EXPLAIN {sql_query}")
				return True, None
			except Exception as e:
				return False, f"SQL syntax error: {e}"
				
		except Exception as e:
			return False, f"Validation error: {e}"
	
	def execute_sql(self, sql_query: str) -> Tuple[bool, Optional[pd.DataFrame], Optional[str]]:
		"""
		Execute SQL query and return results.
		Returns (success, dataframe, error_message).
		"""
		try:
			# Validate first
			is_valid, error_msg = self.validate_sql(sql_query)
			if not is_valid:
				return False, None, error_msg
			
			# Execute query
			result = self.conn.execute(sql_query)
			df = result.df()
			
			info(f"SQL executed successfully, returned {len(df)} rows")
			return True, df, None
			
		except Exception as e:
			error_msg = f"SQL execution failed: {e}"
			error(error_msg)
			return False, None, error_msg
	
	def get_table_sample(self, table_name: str, limit: int = 5) -> Optional[pd.DataFrame]:
		"""Get a sample of data from a table."""
		try:
			result = self.conn.execute(f"SELECT * FROM {table_name} LIMIT {limit}")
			return result.df()
		except Exception as e:
			warn(f"Failed to get sample from {table_name}: {e}")
			return None
	
	def close(self):
		"""Close database connection."""
		if self.conn:
			self.conn.close()
			info("Database connection closed")
