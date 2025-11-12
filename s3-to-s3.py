#!/usr/bin/env python3
import boto3
import os
from math import ceil
from tqdm import tqdm
import argparse
from botocore.exceptions import ClientError


def get_s3_client(profile_name="default"):
    session = boto3.Session(profile_name=profile_name)
    return session.client("s3")


def multipart_copy_object(s3, bucket, source_key, dest_key, storage_class="GLACIER_IR", part_size=512 * 1024 * 1024):
    """
    Perform multipart copy of large object within the same bucket.
    Supports storage class change and progress bar.
    """
    head = s3.head_object(Bucket=bucket, Key=source_key)
    total_size = head["ContentLength"]
    num_parts = ceil(total_size / part_size)
    print(f"\nStarting multipart copy: {source_key} → {dest_key}")
    print(f"Total size: {total_size / (1024 * 1024):.2f} MB, Parts: {num_parts}")

    # 1️⃣ Initiate multipart upload
    resp = s3.create_multipart_upload(
        Bucket=bucket,
        Key=dest_key,
        StorageClass=storage_class
    )
    upload_id = resp["UploadId"]

    parts = []
    progress = tqdm(total=total_size, unit="B", unit_scale=True, desc="Copying", dynamic_ncols=True)

    try:
        for part_num in range(1, num_parts + 1):
            start = (part_num - 1) * part_size
            end = min(start + part_size, total_size) - 1

            copy_source = {"Bucket": bucket, "Key": source_key}

            copy_resp = s3.upload_part_copy(
                Bucket=bucket,
                Key=dest_key,
                CopySource=copy_source,
                CopySourceRange=f"bytes={start}-{end}",
                UploadId=upload_id,
                PartNumber=part_num
            )

            etag = copy_resp["CopyPartResult"]["ETag"]
            parts.append({"ETag": etag, "PartNumber": part_num})
            progress.update(min(part_size, total_size - start))

        # 2️⃣ Complete upload
        s3.complete_multipart_upload(
            Bucket=bucket,
            Key=dest_key,
            MultipartUpload={"Parts": parts},
            UploadId=upload_id
        )
        progress.close()
        print(f"✅ Copy complete: {dest_key}")

    except Exception as e:
        progress.close()
        print(f"❌ Copy failed: {e}")
        print("Aborting multipart upload...")
        s3.abort_multipart_upload(Bucket=bucket, Key=dest_key, UploadId=upload_id)
        raise


def main():
    parser = argparse.ArgumentParser(
        description="Copy a large S3 object within the same bucket using multipart copy."
    )
    parser.add_argument("--bucket", required=True, help="S3 bucket name")
    parser.add_argument("--source", required=True, help="Source object key")
    parser.add_argument("--dest", required=True, help="Destination object key")
    parser.add_argument("--profile", default="saml", help="AWS CLI profile name (default: saml)")
    parser.add_argument("--storage", default="GLACIER_IR", help="Target storage class (default: GLACIER_IR)")
    args = parser.parse_args()

    s3 = get_s3_client(args.profile)
    multipart_copy_object(s3, args.bucket, args.source, args.dest, args.storage)


if __name__ == "__main__":
    main()
