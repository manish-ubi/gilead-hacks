import os
import json
import time
from typing import Any, Dict, List, Optional
from datetime import datetime

from .aws_helpers import get_dynamodb_resource
from .logging_utils import info, debug, warn, error


class FeedbackSystem:
	"""System for collecting and managing user feedback on responses."""
	
	def __init__(self, table_name: str = "agentic_qa_feedback"):
		self.table_name = table_name
		self.table = self._get_table()
	
	def _get_table(self):
		"""Get DynamoDB table for feedback."""
		try:
			db = get_dynamodb_resource()
			return db.Table(self.table_name)
		except Exception as e:
			warn(f"Feedback table unavailable: {e}")
			return None
	
	def record_feedback(
		self, 
		query_hash: str, 
		query: str, 
		response: str, 
		feedback_type: str,  # 'positive' or 'negative'
		user_id: Optional[str] = None,
		additional_notes: Optional[str] = None
	) -> bool:
		"""
		Record user feedback for a query/response pair.
		Returns True if successful.
		"""
		if not self.table:
			warn("Feedback table not available")
			return False
		
		try:
			timestamp = int(time.time())
			feedback_id = f"{query_hash}_{timestamp}"
			
			item = {
				"feedback_id": feedback_id,
				"query_hash": query_hash,
				"query": query,
				"response": response,
				"feedback_type": feedback_type,
				"user_id": user_id or "anonymous",
				"timestamp": timestamp,
				"created_at": datetime.utcnow().isoformat(),
				"additional_notes": additional_notes or "",
				"ttl": timestamp + (30 * 24 * 60 * 60)  # 30 days TTL
			}
			
			self.table.put_item(Item=item)
			info(f"Recorded {feedback_type} feedback for query: {query[:50]}...")
			return True
			
		except Exception as e:
			error(f"Failed to record feedback: {e}")
			return False
	
	def get_feedback_stats(self, query_hash: Optional[str] = None) -> Dict[str, Any]:
		"""Get feedback statistics."""
		if not self.table:
			return {"error": "Feedback table not available"}
		
		try:
			# Build scan parameters
			scan_kwargs = {}
			if query_hash:
				scan_kwargs["FilterExpression"] = "query_hash = :qh"
				scan_kwargs["ExpressionAttributeValues"] = {":qh": query_hash}
			
			# Scan for feedback
			response = self.table.scan(**scan_kwargs)
			feedback_items = response.get("Items", [])
			
			# Handle pagination
			while "LastEvaluatedKey" in response:
				scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
				response = self.table.scan(**scan_kwargs)
				feedback_items.extend(response.get("Items", []))
			
			# Calculate statistics
			total_feedback = len(feedback_items)
			positive_count = sum(1 for item in feedback_items if item.get("feedback_type") == "positive")
			negative_count = sum(1 for item in feedback_items if item.get("feedback_type") == "negative")
			
			stats = {
				"total_feedback": total_feedback,
				"positive_count": positive_count,
				"negative_count": negative_count,
				"positive_ratio": positive_count / total_feedback if total_feedback > 0 else 0,
				"negative_ratio": negative_count / total_feedback if total_feedback > 0 else 0
			}
			
			if query_hash:
				stats["query_hash"] = query_hash
			
			return stats
			
		except Exception as e:
			error(f"Failed to get feedback stats: {e}")
			return {"error": str(e)}
	
	def get_recent_feedback(self, limit: int = 10) -> List[Dict[str, Any]]:
		"""Get recent feedback entries."""
		if not self.table:
			return []
		
		try:
			response = self.table.scan(
				Limit=limit,
				ScanIndexForward=False  # Most recent first
			)
			
			feedback_items = response.get("Items", [])
			
			# Sort by timestamp (most recent first)
			feedback_items.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
			
			return feedback_items[:limit]
			
		except Exception as e:
			error(f"Failed to get recent feedback: {e}")
			return []
	
	def get_feedback_for_query(self, query_hash: str) -> List[Dict[str, Any]]:
		"""Get all feedback for a specific query."""
		if not self.table:
			return []
		
		try:
			response = self.table.scan(
				FilterExpression="query_hash = :qh",
				ExpressionAttributeValues={":qh": query_hash}
			)
			
			feedback_items = response.get("Items", [])
			
			# Handle pagination
			while "LastEvaluatedKey" in response:
				response = self.table.scan(
					FilterExpression="query_hash = :qh",
					ExpressionAttributeValues={":qh": query_hash},
					ExclusiveStartKey=response["LastEvaluatedKey"]
				)
				feedback_items.extend(response.get("Items", []))
			
			# Sort by timestamp (most recent first)
			feedback_items.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
			
			return feedback_items
			
		except Exception as e:
			error(f"Failed to get feedback for query: {e}")
			return []
	
	def cleanup_old_feedback(self, days_old: int = 30) -> int:
		"""Clean up feedback older than specified days."""
		if not self.table:
			return 0
		
		try:
			cutoff_time = int(time.time()) - (days_old * 24 * 60 * 60)
			
			response = self.table.scan(
				FilterExpression="timestamp < :cutoff",
				ExpressionAttributeValues={":cutoff": cutoff_time}
			)
			
			deleted_count = 0
			for item in response.get("Items", []):
				self.table.delete_item(Key={"feedback_id": item["feedback_id"]})
				deleted_count += 1
			
			# Handle pagination
			while "LastEvaluatedKey" in response:
				response = self.table.scan(
					FilterExpression="timestamp < :cutoff",
					ExpressionAttributeValues={":cutoff": cutoff_time},
					ExclusiveStartKey=response["LastEvaluatedKey"]
				)
				for item in response.get("Items", []):
					self.table.delete_item(Key={"feedback_id": item["feedback_id"]})
					deleted_count += 1
			
			if deleted_count > 0:
				info(f"Cleaned up {deleted_count} old feedback entries")
			
			return deleted_count
			
		except Exception as e:
			error(f"Failed to cleanup old feedback: {e}")
			return 0
