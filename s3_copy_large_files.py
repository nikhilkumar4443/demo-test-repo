#!/usr/bin/env python3
import boto3
import os
import argparse
from tqdm import tqdm
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


def copy_objects_with_progress(s3_client, bucket, source_objects, source_prefix, dest_prefix=""):
    """Copy all objects with progress bar"""
    total_size = sum(obj["Size"] for obj in source_objects)
    copied_size = 0

    with tqdm(total=total_size, unit="B", unit_scale=True, desc="Copying files") as pbar:
        for obj in source_objects:
            source_key = obj["Key"]
            dest_key = os.path.join(dest_prefix, os.path.basename(source_key)) if dest_prefix else os.path.basename(source_key)
            copy_source = {"Bucket": bucket, "Key": source_key}

            # Perform S3 server-side copy
            s3_client.copy_object(CopySource=copy_source, Bucket=bucket, Key=dest_key)

            # Update progress bar (since copy_object is atomic, we assume full file copied)
            copied_size += obj["Size"]
            pbar.update(obj["Size"])


def delete_objects(s3_client, bucket, prefix):
    """Delete all objects under a given prefix"""
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        objects_to_delete = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
        if objects_to_delete:
            s3_client.delete_objects(Bucket=bucket, Delete={"Objects": objects_to_delete})
            print(f"Deleted {len(objects_to_delete)} objects from {prefix}")


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
    dest_prefix = ""  # root

    # ---- Step 1: Create S3 Client ----
    s3 = BrokenPipeError
    # ---- Step 2: Get source folder details ----
    print(f"\nGetting details for source: s3://{bucket}/{source_prefix}")
    src_count, src_size, src_objects = get_folder_details(s3, bucket, source_prefix)
    print(f"Source - Objects: {src_count}, Total size: {src_size / (1024*1024):.2f} MB")

    if src_count == 0:
        print("❌ No objects found in the source path. Exiting.")
        return

    # ---- Step 3: Copy to root with progress ----
    print("\nStarting copy to root...")
    copy_objects_with_progress(s3, bucket, src_objects, source_prefix, dest_prefix)

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
