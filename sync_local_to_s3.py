import argparse
import os
from typing import List

try:
	from .aws_helpers import get_s3_client
	from .logging_utils import info
except ImportError:
	from aws_helpers import get_s3_client
	from logging_utils import info


def list_pdfs(local_dir: str) -> List[str]:
	pdfs: List[str] = []
	for root, _dirs, files in os.walk(local_dir):
		for f in files:
			if f.lower().endswith((".pdf", ".png")):
				pdfs.append(os.path.join(root, f))
	return pdfs


def upload_pdfs(local_dir: str, bucket: str, prefix: str = "") -> None:
	s3 = get_s3_client()
	files = list_pdfs(local_dir)
	info(f"Uploading {len(files)} PDFs to s3://{bucket}/{prefix}")
	for path in files:
		key = os.path.join(prefix, os.path.basename(path)).replace("\\", "/")
		# Skip if same-sized object already exists
		try:
			head = s3.head_object(Bucket=bucket, Key=key)
			size_remote = int(head.get("ContentLength", -1))
			size_local = os.path.getsize(path)
			if size_remote == size_local:
				info(f"Skip upload (exists, same size): {path} -> s3://{bucket}/{key}")
				continue
		except Exception:
			pass
		info(f"Uploading {path} -> s3://{bucket}/{key}")
		s3.upload_file(path, bucket, key)


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("--dir", required=True, help="Local directory with PDFs")
	parser.add_argument("--bucket", required=True)
	parser.add_argument("--prefix", default="")
	args = parser.parse_args()

	upload_pdfs(args.dir, args.bucket, args.prefix)


if __name__ == "__main__":
	main()
