#!/usr/bin/env python3
import os

import aws_cdk as cdk

from lib.stacks.mercury_stack import MercuryStack

app = cdk.App()
env = cdk.Environment(
    account=os.environ["CDK_DEFAULT_ACCOUNT"], region=os.environ["CDK_DEFAULT_REGION"]
)
MercuryStack(app, "MercuryStack", env=env)
app.synth()
