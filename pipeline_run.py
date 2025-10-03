import argparse
import json

from .sync_local_to_s3 import upload_pdfs
from .ingest_textract import process_key
from .aws_helpers import s3_list
from .aws_helpers import start_kb_sync
from .logging_utils import info


def run_pipeline(local_dir: str, bucket: str, kb_id: str, ds_id: str, pdf_prefix: str = "raw/", processed_prefix: str = "processed/") -> None:
	# 1) Upload PDFs
	upload_pdfs(local_dir, bucket, pdf_prefix)
	# 2) Textract each uploaded PDF
	keys = [k for k in s3_list(bucket, pdf_prefix) if k.lower().endswith(".pdf")]
	info(f"Found {len(keys)} PDFs to process")
	outputs = []
	for k in keys:
		okey = process_key(bucket, k, processed_prefix)
		outputs.append(okey)
	info(f"Processed {len(outputs)} files to {processed_prefix}")
	# 3) KB sync without re-parsing CLI args
	info(f"Triggering KB sync kb={kb_id} ds={ds_id}")
	job_id = start_kb_sync(kb_id, ds_id)
	info(f"KB ingestion job started id={job_id}")


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("--dir", required=True, help="Local directory containing PDFs")
	parser.add_argument("--bucket", required=True)
	parser.add_argument("--kb-id", required=True)
	parser.add_argument("--ds-id", required=True)
	parser.add_argument("--pdf-prefix", default="raw/")
	parser.add_argument("--processed-prefix", default="processed/")
	args = parser.parse_args()

	run_pipeline(args.dir, args.bucket, args.kb_id, args.ds_id, args.pdf_prefix, args.processed_prefix)


if __name__ == "__main__":
	main()
