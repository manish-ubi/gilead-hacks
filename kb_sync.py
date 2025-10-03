import argparse
import json

from .aws_helpers import start_kb_sync
from .logging_utils import info


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("--kb-id", required=True, help="Knowledge Base ID")
	parser.add_argument("--ds-id", required=True, help="Data Source ID linked to the KB")
	args = parser.parse_args()

	info(f"Triggering KB sync kb={args.kb_id} ds={args.ds_id}")
	job_id = start_kb_sync(args.kb_id, args.ds_id)
	info(f"KB ingestion job started id={job_id}")
	print(json.dumps({"ingestion_job_id": job_id}))


if __name__ == "__main__":
	main()
