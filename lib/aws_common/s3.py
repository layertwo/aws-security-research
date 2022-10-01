from typing import Any

from aws_cdk import RemovalPolicy
from aws_cdk import aws_s3 as s3
from constructs import Construct


def build_bucket(scope: Construct, bucket_id: str, **kwargs: Any) -> s3.Bucket:
    return s3.Bucket(
        scope,
        bucket_id,
        bucket_name=bucket_id,
        block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        encryption=s3.BucketEncryption.S3_MANAGED,
        enforce_ssl=True,
        versioned=True,
        removal_policy=RemovalPolicy.RETAIN,
        **kwargs,
    )
