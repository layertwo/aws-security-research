from typing import Any

from aws_cdk.aws_ec2 import SecurityGroup, Vpc
from constructs import Construct


def build_security_group(scope: Construct, vpc: Vpc, name: str, **kwargs: Any) -> SecurityGroup:
    return SecurityGroup(
        scope,
        f"{name}-sg",
        vpc=vpc,
        description=f"{name.capitalize()} security group",
        **kwargs,
    )
