import argparse
import os
from typing import Dict, List

from .aws_helpers import get_kendra_client, get_s3_client


def list_processed(bucket: str, prefix: str) -> List[str]:
	s3 = get_s3_client()
	keys: List[str] = []
	continuation = None
	while True:
		kwargs = {"Bucket": bucket, "Prefix": prefix}
		if continuation:
			kwargs["ContinuationToken"] = continuation
		resp = s3.list_objects_v2(**kwargs)
		for it in resp.get("Contents", []):
			if it["Key"].endswith(".txt"):
				keys.append(it["Key"])
		if resp.get("IsTruncated"):
			continuation = resp.get("NextContinuationToken")
			continue
		break
	return keys


def kendra_batch_put(index_id: str, bucket: str, keys: List[str]) -> None:
	kendra = get_kendra_client()
	documents = []
	for key in keys:
		doc_id = key.replace("/", "_")
		attributes = [
			{"Key": "_document_title", "Value": {"StringValue": os.path.basename(key)}},
		]
		documents.append({
			"Id": doc_id,
			"S3Path": {"Bucket": bucket, "Key": key},
			"Attributes": attributes,
			"ContentType": "PLAIN_TEXT",
		})
		if len(documents) == 5:
			kendra.batch_put_document(IndexId=index_id, Documents=documents)
			documents = []
	if documents:
		kendra.batch_put_document(IndexId=index_id, Documents=documents)


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("--bucket", required=True)
	parser.add_argument("--index-id", required=True)
	parser.add_argument("--prefix", default="processed/")
	args = parser.parse_args()

	keys = list_processed(args.bucket, args.prefix)
	if not keys:
		print("No processed documents found.")
		return
	kendra_batch_put(args.index_id, args.bucket, keys)
	print(f"Indexed {len(keys)} documents into Kendra {args.index_id}")


if __name__ == "__main__":
	main()
