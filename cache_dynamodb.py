import os
import time
from typing import Any, Dict, Optional
from datetime import datetime, timedelta

from .aws_helpers import get_dynamodb_resource
from .logging_utils import info, debug, warn, error


DEFAULT_TTL_SECONDS = 60 * 60 * 24  # 1 day
CACHE_CLEANUP_INTERVAL = 60 * 60  # 1 hour


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
		created_at = int(time.time())
		item = {
			"query_hash": query_hash,
			"retrieved_docs": retrieved_docs,
			"answer": answer,
			"ttl": expire_at,
			"created_at": created_at,
			"access_count": 0,
			"last_accessed": created_at,
		}
		table.put_item(Item=item)
		debug("Cache stored")
	except Exception as e:
		warn(f"DDB put_item failed: {e}")
		return


def invalidate_cache(query_hash: Optional[str] = None, pattern: Optional[str] = None) -> int:
	"""
	Invalidate cache entries.
	- If query_hash provided: invalidate specific entry
	- If pattern provided: invalidate entries matching pattern
	- If neither provided: invalidate all entries
	Returns number of entries invalidated.
	"""
	table = _table()
	if table is None:
		return 0
	
	try:
		if query_hash:
			# Invalidate specific entry
			table.delete_item(Key={"query_hash": query_hash})
			info(f"Invalidated cache entry: {query_hash[:8]}...")
			return 1
		else:
			# Scan and delete all entries (or matching pattern)
			scan_kwargs = {}
			if pattern:
				scan_kwargs["FilterExpression"] = "contains(query_hash, :pattern)"
				scan_kwargs["ExpressionAttributeValues"] = {":pattern": pattern}
			
			deleted_count = 0
			response = table.scan(**scan_kwargs)
			
			for item in response.get("Items", []):
				table.delete_item(Key={"query_hash": item["query_hash"]})
				deleted_count += 1
			
			# Handle pagination
			while "LastEvaluatedKey" in response:
				scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
				response = table.scan(**scan_kwargs)
				for item in response.get("Items", []):
					table.delete_item(Key={"query_hash": item["query_hash"]})
					deleted_count += 1
			
			info(f"Invalidated {deleted_count} cache entries")
			return deleted_count
	except Exception as e:
		warn(f"Cache invalidation failed: {e}")
		return 0


def cleanup_expired_cache() -> int:
	"""Remove expired cache entries. Returns number of entries cleaned up."""
	table = _table()
	if table is None:
		return 0
	
	try:
		current_time = int(time.time())
		response = table.scan(
			FilterExpression="ttl < :current_time",
			ExpressionAttributeValues={":current_time": current_time}
		)
		
		deleted_count = 0
		for item in response.get("Items", []):
			table.delete_item(Key={"query_hash": item["query_hash"]})
			deleted_count += 1
		
		# Handle pagination
		while "LastEvaluatedKey" in response:
			response = table.scan(
				FilterExpression="ttl < :current_time",
				ExpressionAttributeValues={":current_time": current_time},
				ExclusiveStartKey=response["LastEvaluatedKey"]
			)
			for item in response.get("Items", []):
				table.delete_item(Key={"query_hash": item["query_hash"]})
				deleted_count += 1
		
		if deleted_count > 0:
			info(f"Cleaned up {deleted_count} expired cache entries")
		return deleted_count
	except Exception as e:
		warn(f"Cache cleanup failed: {e}")
		return 0


def get_cache_stats() -> Dict[str, Any]:
	"""Get cache statistics."""
	table = _table()
	if table is None:
		return {"error": "DynamoDB table not available"}
	
	try:
		response = table.scan(Select="COUNT")
		total_items = response.get("Count", 0)
		
		# Get access statistics
		response = table.scan()
		access_counts = []
		created_times = []
		
		for item in response.get("Items", []):
			access_counts.append(item.get("access_count", 0))
			created_times.append(item.get("created_at", 0))
		
		# Handle pagination for stats
		while "LastEvaluatedKey" in response:
			response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
			for item in response.get("Items", []):
				access_counts.append(item.get("access_count", 0))
				created_times.append(item.get("created_at", 0))
		
		stats = {
			"total_entries": total_items,
			"avg_access_count": sum(access_counts) / len(access_counts) if access_counts else 0,
			"max_access_count": max(access_counts) if access_counts else 0,
			"oldest_entry": min(created_times) if created_times else None,
			"newest_entry": max(created_times) if created_times else None,
		}
		
		if stats["oldest_entry"]:
			stats["oldest_entry_age_hours"] = (current_time - stats["oldest_entry"]) / 3600
		if stats["newest_entry"]:
			stats["newest_entry_age_hours"] = (current_time - stats["newest_entry"]) / 3600
			
		return stats
	except Exception as e:
		warn(f"Failed to get cache stats: {e}")
		return {"error": str(e)}


def update_access_stats(query_hash: str) -> None:
	"""Update access statistics for a cache entry."""
	table = _table()
	if table is None:
		return
	
	try:
		current_time = int(time.time())
		table.update_item(
			Key={"query_hash": query_hash},
			UpdateExpression="SET access_count = access_count + :inc, last_accessed = :current_time",
			ExpressionAttributeValues={":inc": 1, ":current_time": current_time}
		)
		debug(f"Updated access stats for {query_hash[:8]}...")
	except Exception as e:
		warn(f"Failed to update access stats: {e}")
