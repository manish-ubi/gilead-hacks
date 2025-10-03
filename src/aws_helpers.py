import hashlib
import json
import os
from typing import Any, Dict, List, Optional, Tuple

import boto3
from .logging_utils import info, debug, warn, error

# Memoized AWS session and clients to avoid repeated creation per container
_CACHED_SESSION: Optional[boto3.session.Session] = None
_CLIENT_CACHE: Dict[str, Any] = {}
_RESOURCE_CACHE: Dict[str, Any] = {}


def _session():
    global _CACHED_SESSION
    if _CACHED_SESSION is not None:
        return _CACHED_SESSION
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
    if region:
        debug(f"Using AWS region: {region}")
        _CACHED_SESSION = boto3.session.Session(region_name=region)
    else:
        _CACHED_SESSION = boto3.session.Session()
    return _CACHED_SESSION


def get_s3_client():
    if "s3" not in _CLIENT_CACHE:
        debug("Creating S3 client")
        _CLIENT_CACHE["s3"] = _session().client("s3")
    return _CLIENT_CACHE["s3"]


def get_textract_client():
    if "textract" not in _CLIENT_CACHE:
        debug("Creating Textract client")
        _CLIENT_CACHE["textract"] = _session().client("textract")
    return _CLIENT_CACHE["textract"]


def get_kendra_client():
    if "kendra" not in _CLIENT_CACHE:
        debug("Creating Kendra client")
        _CLIENT_CACHE["kendra"] = _session().client("kendra")
    return _CLIENT_CACHE["kendra"]


def get_dynamodb_resource():
    if "dynamodb" not in _RESOURCE_CACHE:
        debug("Creating DynamoDB resource")
        _RESOURCE_CACHE["dynamodb"] = _session().resource("dynamodb")
    return _RESOURCE_CACHE["dynamodb"]


def get_lambda_client():
    if "lambda" not in _CLIENT_CACHE:
        debug("Creating Lambda client")
        _CLIENT_CACHE["lambda"] = _session().client("lambda")
    return _CLIENT_CACHE["lambda"]


def get_bedrock_client():
    if "bedrock-runtime" not in _CLIENT_CACHE:
        debug("Creating Bedrock Runtime client")
        _CLIENT_CACHE["bedrock-runtime"] = _session().client("bedrock-runtime")
    return _CLIENT_CACHE["bedrock-runtime"]


def get_bedrock_agent_client():
    if "bedrock-agent" not in _CLIENT_CACHE:
        debug("Creating Bedrock Agent client")
        _CLIENT_CACHE["bedrock-agent"] = _session().client("bedrock-agent")
    return _CLIENT_CACHE["bedrock-agent"]


def get_bedrock_agent_runtime_client():
    if "bedrock-agent-runtime" not in _CLIENT_CACHE:
        debug("Creating Bedrock Agent Runtime client")
        _CLIENT_CACHE["bedrock-agent-runtime"] = _session().client("bedrock-agent-runtime")
    return _CLIENT_CACHE["bedrock-agent-runtime"]


def s3_put_text(bucket: str, key: str, text: str) -> None:
	info(f"S3 put text: s3://{bucket}/{key} ({len(text)} bytes)")
	s3 = get_s3_client()
	s3.put_object(Bucket=bucket, Key=key, Body=text.encode("utf-8"), ContentType="text/plain")


def s3_get_text(bucket: str, key: str) -> str:
	info(f"S3 get text: s3://{bucket}/{key}")
	s3 = get_s3_client()
	obj = s3.get_object(Bucket=bucket, Key=key)
	return obj["Body"].read().decode("utf-8")


def s3_list(bucket: str, prefix: str = "") -> List[str]:
	info(f"S3 list: s3://{bucket}/{prefix}")
	s3 = get_s3_client()
	keys: List[str] = []
	continuation: Optional[str] = None
	while True:
		kwargs: Dict[str, Any] = {"Bucket": bucket, "Prefix": prefix}
		if continuation:
			kwargs["ContinuationToken"] = continuation
		resp = s3.list_objects_v2(**kwargs)
		for it in resp.get("Contents", []):
			keys.append(it["Key"])
		if resp.get("IsTruncated"):
			continuation = resp.get("NextContinuationToken")
			continue
		break
	info(f"Listed {len(keys)} keys")
	return keys


def kendra_query(index_id: str, query_text: str, top_k: int = 5) -> List[Dict[str, Any]]:
	info(f"Kendra query top_k={top_k}")
	kendra = get_kendra_client()
	resp = kendra.query(
		IndexId=index_id,
		QueryText=query_text,
		PageSize=top_k,
	)
	results = []
	for item in resp.get("ResultItems", []):
		if item.get("Type") in ("ANSWER", "DOCUMENT", "PASSAGE"):
			text = None
			if "DocumentExcerpt" in item and item["DocumentExcerpt"].get("Text"):
				text = item["DocumentExcerpt"]["Text"]
			elif "AdditionalAttributes" in item:
				for attr in item["AdditionalAttributes"]:
					if attr.get("Key") == "AnswerText":
						text = attr.get("Value", {}).get("TextWithHighlightsValue", {}).get("Text")
			if text:
				results.append({
					"DocumentId": item.get("DocumentId"),
					"ScoreAttributes": item.get("ScoreAttributes"),
					"Text": text,
				})
	info(f"Kendra returned {len(results)} results")
	return results


def invoke_bedrock(messages: List[Dict[str, str]], model_id: Optional[str] = None, max_tokens: int = 400, temperature: float = 0.2) -> str:
	model_id = model_id or os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-3-sonnet-20240229-v1:0")
	info(f"Invoke Bedrock model={model_id} max_tokens={max_tokens} temp={temperature}")
	client = get_bedrock_client()
	body = {
		"anthropic_version": "bedrock-2023-05-31",
		"messages": messages,
		"max_tokens": max_tokens,
		"temperature": temperature,
	}
	resp = client.invoke_model(modelId=model_id, body=json.dumps(body))
	payload = json.loads(resp["body"].read())
	content = payload.get("content", [])
	text = ""
	if content and isinstance(content, list):
		for block in content:
			if block.get("type") == "text" and block.get("text"):
				text = block["text"].strip()
	info(f"Bedrock output length={len(text)}")
	return text


def hash_query(query: str) -> str:
	h = hashlib.sha256(query.encode("utf-8")).hexdigest()
	debug(f"Query hash={h[:8]}...")
	return h


def start_kb_sync(knowledge_base_id: str, data_source_id: str) -> str:
	info(f"Start KB sync kb={knowledge_base_id} ds={data_source_id}")
	client = get_bedrock_agent_client()
	resp = client.start_ingestion_job(knowledgeBaseId=knowledge_base_id, dataSourceId=data_source_id)
	jid = resp["ingestionJob"].get("ingestionJobId", "")
	info(f"Started ingestion job id={jid}")
	return jid


def invoke_agent(agent_id: str, agent_alias_id: str, prompt: str, session_id: Optional[str] = None) -> str:
	info(f"Invoke Agent id={agent_id} alias={agent_alias_id}")
	runtime = get_bedrock_agent_runtime_client()
	if session_id is None:
		import uuid
		session_id = str(uuid.uuid4())
	resp = runtime.invoke_agent(agentId=agent_id, agentAliasId=agent_alias_id, sessionId=session_id, inputText=prompt)
	chunks: List[str] = []
	try:
		stream = resp.get("completion")
		if stream is None:
			warn("No completion stream returned from agent")
			return ""
		for event in stream:
			if "chunk" in event and event["chunk"].get("bytes"):
				try:
					piece = event["chunk"]["bytes"].decode("utf-8")
					chunks.append(piece)
				except Exception:
					pass
	finally:
		try:
			stream.close()  # type: ignore[attr-defined]
		except Exception:
			pass
	text = "".join(chunks).strip()
	info(f"Agent output length={len(text)}")
	return text
