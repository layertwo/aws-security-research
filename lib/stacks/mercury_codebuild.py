from typing import Dict, List

import aws_cdk.aws_codebuild as codebuild
import aws_cdk.aws_codepipeline as codepipeline
import aws_cdk.aws_codepipeline_actions as codepipeline_actions
import aws_cdk.aws_events as events
import aws_cdk.aws_events_targets as events_targets
import aws_cdk.aws_s3 as s3
import aws_cdk.aws_ssm as ssm
from aws_cdk import Duration, SecretValue, Stack
from constructs import Construct

from lib.aws_common.s3 import SecureBucket


class MercuryCodeBuild(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.artifacts_bucket = self.build_bucket(
            bucket_id="MercuryArtifactBucket", bucket_name="mercury-codebuild-artifacts"
        )
        self.package_bucket = self.build_bucket(
            bucket_id="MercuryPackageBucket", bucket_name="mercury-package-bucket"
        )
        pipeline = codepipeline.Pipeline(
            self,
            "CodePipeline",
            pipeline_name="MercuryPipeline",
            artifact_bucket=self.artifacts_bucket,
        )

        # Add a source stage to the pipeline
        source_output = codepipeline.Artifact("SourceArtifact")
        source_action = codepipeline_actions.GitHubSourceAction(
            action_name="GitHub_Source",
            owner="cisco",
            repo="mercury",
            oauth_token=SecretValue.secrets_manager("layertwo-github-secret"),
            branch="main",
            trigger=codepipeline_actions.GitHubTrigger.POLL,
            output=source_output,
        )
        pipeline.add_stage(
            stage_name="Source",
            actions=[source_action],
        )

        # Add a build stage to the pipeline
        project = self.build_project(arch="arm")
        build_output = codepipeline.Artifact("MercuryBuildArtifact")
        build_action = codepipeline_actions.CodeBuildAction(
            action_name="CodeBuild",
            project=project,
            input=source_output,
            outputs=[build_output],
        )
        pipeline.add_stage(
            stage_name="Build",
            actions=[build_action],
        )

        # Create an SSM parameter to store the artifact name
        ssm_parameter = ssm.StringParameter(
            self,
            "MercurySsmParameter",
            parameter_name="MercurySsmParameter",
            string_value=build_output.at_path("mercury-1.0.rpm").location,
        )

        # Grant the CodeBuild project permission to write to the SSM parameter
        ssm_parameter.grant_write(project)

        # S3 Deploy
        s3_deploy_action = codepipeline_actions.S3DeployAction(
            action_name="S3Deploy",
            bucket=self.package_bucket,
            input=build_output,
        )

        # Add Deploy stage to the pipeline
        pipeline.add_stage(stage_name="Deploy", actions=[s3_deploy_action])

    def build_bucket(self, bucket_id: str, bucket_name: str) -> SecureBucket:
        """Build bucket to store CodeBuild artifacts"""
        return SecureBucket(
            self,
            bucket_id=bucket_id,
            bucket_name=bucket_name,
            lifecycle_rules=[
                s3.LifecycleRule(
                    transitions=[
                        s3.Transition(
                            storage_class=s3.StorageClass.ONE_ZONE_INFREQUENT_ACCESS,
                            transition_after=Duration.days(30),
                        )
                    ]
                )
            ],
        )

    def build_project(self, arch: str = "x86") -> codebuild.Project:
        environments: Dict[str, LinuxBuildImage] = {
            "x86": codebuild.LinuxBuildImage.AMAZON_LINUX_2_4,
            "arm": codebuild.LinuxBuildImage.AMAZON_LINUX_2_ARM_2,
        }

        image = environments[arch]
        return codebuild.Project(
            self,
            f"MercuryProject{arch.capitalize()}",
            build_spec=self.build_spec,
            source=self.source,
            concurrent_build_limit=1,
            environment=codebuild.BuildEnvironment(
                build_image=image, compute_type=codebuild.ComputeType.SMALL
            ),
            project_name=f"mercury-codebuild-{arch}",
            cache=codebuild.Cache.local(codebuild.LocalCacheMode.SOURCE),
            artifacts=codebuild.Artifacts.s3(
               bucket=self.artifacts_bucket,
               include_build_id=False,
               package_zip=False,
            ),
        )

    @property
    def source(self) -> codebuild.Source:
        return codebuild.Source.git_hub(owner="cisco", repo="mercury", clone_depth=1)

    @property
    def build_spec(self) -> codebuild.BuildSpec:
        yum_deps = [
            "gcc10",
            "gcc10-c++",
            "zlib-devel",
            "openssl-devel",
            "kernel-devel",
            "autoconf",
            "libasan10",
            "rpm-build",
            "squashfs-tools",
        ]
        return codebuild.BuildSpec.from_object(
            {
                "version": "0.2",
                "env": {"variables": {"CC": "/usr/bin/gcc10-gcc", "CXX": "/usr/bin/gcc10-c++"}},
                "phases": {
                    "install": {
                        "runtime-versions": {
                            "ruby": "latest",
                        },
                        "commands": [
                            "yum update -y",
                            f"yum install -y {' '.join(yum_deps)}",
                        ],
                    },
                    "build": {
                        "commands": [
                            "./configure CC=$CC CXX=$CXX",
                            "make CC=$CC CXX=$CXX V=s",
                        ]
                    },
                    "post_build": {
                        "commands": [
                            "export MERC_VERSION=$(cat VERSION)",
                            "gem install fpm",
                            "./build_pkg.sh -t rpm",
                        ]
                    },
                },
                "artifacts": {
                    "files": ["*.rpm"],
                    "discard-paths": "yes",
                    "name": "mercury-package",
                },
            }
        )
