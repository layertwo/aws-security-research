#!/usr/bin/env python3
import os

import aws_cdk as cdk

app = cdk.App()
env = cdk.Environment(
    account=os.environ["CDK_DEFAULT_ACCOUNT"], region=os.environ["CDK_DEFAULT_REGION"]
)
app.synth()
