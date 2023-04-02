from aws_cdk import Stack
from aws_cdk.pipelines import CodePipeline, CodePipelineSource, ShellStep
from constructs import Construct

from lib.stacks.mercury_codebuild import MercuryCodeBuild


class MercuryPipelineStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        pipeline = CodePipeline(
            self,
            "MercuryPipeline",
            pipeline_name="Mercury",
            synth=ShellStep(
                "PipelineSynth",
                input=CodePipelineSource.git_hub("layertwo/aws-security-research", "main"),
                commands=[
                    "npm install -g aws-cdk",
                    "python -m pip install -r requirements.txt",
                    "cdk synth",
                ],
            ),
        )
        codebuild = MercuryCodeBuild(scope, "MercuryCodeBuild", env=kwargs["env"])
