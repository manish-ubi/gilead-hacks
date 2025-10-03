import argparse
import json
import os
from typing import Any, Dict, List

import boto3

from .aws_helpers import get_s3_client, get_textract_client, s3_put_text
from .logging_utils import info, debug, warn, error


def start_textract_job(bucket: str, key: str) -> str:
	info(f"Starting Textract job for s3://{bucket}/{key}")
	tx = get_textract_client()
	resp = tx.start_document_text_detection(DocumentLocation={"S3Object": {"Bucket": bucket, "Name": key}})
	jid = resp["JobId"]
	info(f"Textract JobId={jid}")
	return jid


def wait_for_job(job_id: str) -> List[Dict[str, Any]]:
	import time
	info(f"Waiting for Textract job {job_id}")
	tx = get_textract_client()
	while True:
		resp = tx.get_document_text_detection(JobId=job_id)
		status = resp.get("JobStatus")
		debug(f"Job {job_id} status={status}")
		if status == "SUCCEEDED":
			pages: List[Dict[str, Any]] = [resp]
			while resp.get("NextToken"):
				resp = tx.get_document_text_detection(JobId=job_id, NextToken=resp["NextToken"])
				pages.append(resp)
			info(f"Textract job {job_id} SUCCEEDED with {len(pages)} page batch(es)")
			return pages
		elif status in ("FAILED", "PARTIAL_SUCCESS"):
			raise RuntimeError(f"Textract job {job_id} ended with status {status}")
		time.sleep(2)


def pages_to_text(pages: List[Dict[str, Any]]) -> str:
	lines: List[str] = []
	for page in pages:
		for block in page.get("Blocks", []):
			if block.get("BlockType") == "LINE" and block.get("Text"):
				lines.append(block["Text"])
	text = "\n".join(lines)
	info(f"Extracted {len(lines)} lines ({len(text)} bytes)")
	return text


def process_key(bucket: str, key: str, out_prefix: str = "processed/") -> str:
	# Skip if processed output already exists
	from .aws_helpers import get_s3_client
	s3 = get_s3_client()
	base = os.path.basename(key)
	out_key = f"{out_prefix}{base}.txt"
	try:
		s3.head_object(Bucket=bucket, Key=out_key)
		info(f"Skip Textract (processed exists): s3://{bucket}/{out_key}")
		return out_key
	except Exception:
		pass
	job_id = start_textract_job(bucket, key)
	pages = wait_for_job(job_id)
	text = pages_to_text(pages)
	s3_put_text(bucket, out_key, text)
	info(f"Wrote processed text to s3://{bucket}/{out_key}")
	return out_key


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("--bucket", required=True)
	parser.add_argument("--keys", nargs="+", required=True, help="One or more S3 keys (PDFs)")
	parser.add_argument("--out-prefix", default="processed/")
	args = parser.parse_args()

	outputs: List[str] = []
	for k in args.keys:
		okey = process_key(args.bucket, k, args.out_prefix)
		outputs.append(okey)
	print(json.dumps({"outputs": outputs}))


if __name__ == "__main__":
	main()
