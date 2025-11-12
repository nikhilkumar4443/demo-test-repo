#!/usr/bin/env python3
import boto3
import os
import argparse
from tqdm import tqdm
from boto3.s3.transfer import TransferConfig, S3Transfer
from botocore.exceptions import ClientError


def get_s3_client(profile_name="default"):
    """Return boto3 S3 client using the specified AWS CLI profile."""
    session = boto3.Session(profile_name=profile_name)
    return session.client("s3")


def get_folder_details(s3_client, bucket, prefix):
    """Return total number of objects and total size for a given S3 prefix"""
    paginator = s3_client.get_paginator("list_objects_v2")
    total_size = 0
    total_count = 0
    all_objects = []

    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            total_count += 1
            total_size += obj["Size"]
            all_objects.append(obj)

    return total_count, total_size, all_objects


class ProgressBar:
    """Progress bar callback for multipart copy"""
    def __init__(self, total_size):
        self.pbar = tqdm(total=total_size, unit='B', unit_scale=True, desc="Copying")
        self.lock = None

    def __call__(self, bytes_transferred):
        self.pbar.update(bytes_transferred)

    def close(self):
        self.pbar.close()


def copy_objects_with_multipart(s3_client, bucket, source_objects, source_prefix, dest_prefix=""):
    """Copy all objects using multipart upload for large files"""
    # TransferConfig for multipart copy (use multipart for >100 MB)
    config = TransferConfig(
        multipart_threshold=100 * 1024 * 1024,  # 100MB threshold
        multipart_chunksize=100 * 1024 * 1024,  # 100MB parts
        max_concurrency=5,                      # 5 parallel threads
        use_threads=True
    )

    transfer = S3Transfer(client=s3_client, config=config)

    total_size = sum(obj["Size"] for obj in source_objects)
    progress = ProgressBar(total_size)

    for obj in source_objects:
        source_key = obj["Key"]
        dest_key = os.path.join(dest_prefix, os.path.basename(source_key)) if dest_prefix else os.path.basename(source_key)
        copy_source = {"Bucket": bucket, "Key": source_key}
        storage_class = "GLACIER_IR"
        try:
            transfer.copy(copy_source, bucket, dest_key,extra_args={"StorageClass": storage_class},callback=progress)
        except ClientError as e:
            print(f"❌ Failed to copy {source_key}: {e}")
            continue

    progress.close()


def delete_objects(s3_client, bucket, prefix):
    """Delete all objects under a given prefix"""
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        objects_to_delete = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
        if objects_to_delete:
            s3_client.delete_objects(Bucket=bucket, Delete={"Objects": objects_to_delete})
            print(f"Deleted {len(objects_to_delete)} objects from {prefix}")


# ---------- Main ---------- #

def main():
    parser = argparse.ArgumentParser(
        description="Copy S3 folder to root and verify copy before cleanup."
    )
    parser.add_argument("--bucket", required=True, help="S3 bucket name")
    parser.add_argument("--files_path", required=True, help="Files path to copy")

    args = parser.parse_args()

    bucket = args.bucket
    files_path = args.files_path

    source_prefix = files_path
    dest_prefix = ""

    # ---- Step 1: Create S3 Client ----
    s3 = get_s3_client() 

    # ---- Step 2: Get source folder details ----
    print(f"\nGetting details for source: s3://{bucket}/{source_prefix}")
    src_count, src_size, src_objects = get_folder_details(s3, bucket, source_prefix)
    print(f"Source - Objects: {src_count}, Total size: {src_size / (1024*1024):.2f} MB")

    if src_count == 0:
        print("❌ No objects found in the source path. Exiting.")
        return

    # ---- Step 3: Copy to root using multipart ----
    print("\nStarting copy to root (multipart)...")
    copy_objects_with_multipart(s3, bucket, src_objects, source_prefix, dest_prefix)

    # ---- Step 4: Get destination details ----
    print("\nGetting details for destination (root)...")
    dest_count, dest_size, _ = get_folder_details(s3, bucket, dest_prefix)
    print(f"Destination - Objects: {dest_count}, Total size: {dest_size / (1024*1024):.2f} MB")

    # ---- Step 5: Validate ----
    if src_count == dest_count and src_size == dest_size:
        print("\n✅ Copy successful. Cleaning up old path...")
        delete_objects(s3, bucket, source_prefix)
        print("Cleanup completed.")
    else:
        print("\n❌ Copy failed: Object count or size mismatch.")
        print(f"Source: {src_count} objs, {src_size} bytes")
        print(f"Dest: {dest_count} objs, {dest_size} bytes")


if __name__ == "__main__":
    main()
