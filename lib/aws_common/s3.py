from typing import Any, Optional

from aws_cdk import RemovalPolicy
from aws_cdk.aws_s3 import BlockPublicAccess, Bucket, BucketEncryption
from constructs import Construct


class SecureBucket(Bucket):
    def __init__(
        self, scope: Construct, bucket_id, bucket_name: Optional[str] = None, **kwargs: Any
    ):
        super().__init__(
            scope,
            bucket_id,
            bucket_name=bucket_name or bucket_id,
            block_public_access=BlockPublicAccess.BLOCK_ALL,
            encryption=BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            versioned=True,
            removal_policy=RemovalPolicy.RETAIN,
            **kwargs,
        )
