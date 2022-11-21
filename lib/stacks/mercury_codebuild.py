from aws_cdk import Duration, RemovalPolicy, Stack
from aws_cdk.aws_codebuild import (
    Artifacts,
    BuildEnvironment,
    BuildSpec,
    Cache,
    GitHubSourceCredentials,
    LinuxBuildImage,
    LocalCacheMode,
    Project,
    Source,
)
from aws_cdk.aws_events import Rule, Schedule
from aws_cdk.aws_events_targets import CodeBuildProject
from aws_cdk.aws_codedeploy import ServerApplication
from aws_cdk.aws_s3 import BlockPublicAccess, Bucket, LifecycleRule, StorageClass, Transition
from constructs import Construct


class MercuryCodeBuild(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.bucket = self.build_artifacts_bucket()
        self.project = self.build_project()
        self.rule = self.build_project_rule()

    def build_artifacts_bucket(self) -> Bucket:
        return Bucket(
            self,
            "MercuryArtifactBucket",
            bucket_name="mercury-codebuild-artifacts",
            enforce_ssl=True,
            block_public_access=BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.RETAIN,
            lifecycle_rules=[
                LifecycleRule(
                    transitions=[
                        Transition(
                            storage_class=StorageClass.ONE_ZONE_INFREQUENT_ACCESS,
                            transition_after=Duration.days(30),
                        )
                    ]
                )
            ],
        )

    def build_project_rule(self) -> Rule:
        return Rule(
            self,
            "MercuryCodeBuildRule",
            rule_name="mercury-codebuild-rule",
            schedule=Schedule.rate(Duration.days(7)),
            targets=[CodeBuildProject(self.project)],
        )

    def build_project(self) -> Project:
        return Project(
            self,
            "MercuryProject",
            build_spec=self.build_spec,
            source=self.source,
            concurrent_build_limit=1,
            environment=self.build_environment,
            project_name="mercury-codebuild",
            cache=Cache.local(LocalCacheMode.SOURCE),
            artifacts=Artifacts.s3(
                bucket=self.bucket,
                include_build_id=False,
                package_zip=False,
            )
        )

    @property
    def build_environment(self) -> BuildEnvironment:
        return BuildEnvironment(build_image=LinuxBuildImage.AMAZON_LINUX_2_4)

    @property
    def source(self) -> Source:
        return Source.git_hub(owner="cisco", repo="mercury", clone_depth=1)

    @property
    def build_spec(self) -> BuildSpec:
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
        return BuildSpec.from_object(
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
                            f"./configure CC=$CC CXX=$CXX",
                            f"make CC=$CC CXX=$CXX V=s",
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
