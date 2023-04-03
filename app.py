#!/usr/bin/env python3
import os

import aws_cdk as cdk

from lib.stacks import MercuryCodeBuild, MercuryStack

app = cdk.App()
env = cdk.Environment(
    account=os.environ["CDK_DEFAULT_ACCOUNT"], region=os.environ["CDK_DEFAULT_REGION"]
)
codebuild = MercuryCodeBuild(app, "MercuryCodeBuild", env=env)
MercuryStack(app, "MercuryStack", artifacts_bucket=codebuild.artifacts_bucket, env=env)

app.synth()
