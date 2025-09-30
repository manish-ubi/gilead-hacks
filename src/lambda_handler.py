import json
import os
from typing import Any, Dict

from .aws_helpers import hash_query, invoke_agent
from .cache_dynamodb import get_cached_answer, put_cached_answer
from .logging_utils import info, debug, warn, error


GUARDRAIL_APOLOGY = "Sorry, this information is not available in the documents."


def handler(event: Dict[str, Any], _context: Any) -> Dict[str, Any]:
	info("Lambda handler invoked")
	query = event.get("query") or event.get("body") or ""
	if isinstance(query, str) and query.startswith("{"):
		try:
			query = json.loads(query).get("query", "")
		except Exception:
			pass
	if not isinstance(query, str):
		query = str(query)

	if not query.strip():
		warn("Missing query")
		return {"statusCode": 400, "body": json.dumps({"error": "Missing query"})}

	qhash = hash_query(query)
	cached = get_cached_answer(qhash)
	if cached and cached.get("answer"):
		info("Returning cached answer")
		return {"statusCode": 200, "body": json.dumps({"answer": cached["answer"], "cached": True})}

	agent_id = os.getenv("BEDROCK_AGENT_ID", "")
	agent_alias_id = os.getenv("BEDROCK_AGENT_ALIAS_ID", "")
	if not agent_id or not agent_alias_id:
		error("Agent IDs not set")
		return {"statusCode": 500, "body": json.dumps({"error": "BEDROCK_AGENT_ID or BEDROCK_AGENT_ALIAS_ID not set"})}

	answer = invoke_agent(agent_id, agent_alias_id, query) or ""
	if not answer:
		info("Empty answer; using apology")
		answer = GUARDRAIL_APOLOGY

	put_cached_answer(qhash, {"source": "bedrock-agent"}, answer)
	info("Returning fresh answer")
	return {"statusCode": 200, "body": json.dumps({"answer": answer, "cached": False})}


if __name__ == "__main__":
	import sys
	q = sys.argv[1] if len(sys.argv) > 1 else "What is in SPEC-M0778?"
	print(json.dumps(json.loads(handler({"query": q}, None)["body"]), indent=2))
