import os
import time
from typing import Any, Dict, Optional

from .aws_helpers import get_dynamodb_resource
from .logging_utils import info, debug, warn, error


DEFAULT_TTL_SECONDS = 60 * 60 * 24  # 1 day


def _table():
	try:
		tbl_name = os.getenv("DDB_TABLE", "agentic_qa_cache")
		info(f"Using DDB table: {tbl_name}")
		db = get_dynamodb_resource()
		return db.Table(tbl_name)
	except Exception as e:
		warn(f"DDB unavailable: {e}")
		return None


def get_cached_answer(query_hash: str) -> Optional[Dict[str, Any]]:
	table = _table()
	if table is None:
		return None
	try:
		resp = table.get_item(Key={"query_hash": query_hash})
		item = resp.get("Item")
		if item:
			info("Cache hit")
		else:
			debug("Cache miss")
		return item
	except Exception as e:
		warn(f"DDB get_item failed: {e}")
		return None


def put_cached_answer(query_hash: str, retrieved_docs: Any, answer: str, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
	table = _table()
	if table is None:
		return
	try:
		expire_at = int(time.time()) + ttl_seconds
		item = {
			"query_hash": query_hash,
			"retrieved_docs": retrieved_docs,
			"answer": answer,
			"ttl": expire_at,
		}
		table.put_item(Item=item)
		debug("Cache stored")
	except Exception as e:
		warn(f"DDB put_item failed: {e}")
		return
