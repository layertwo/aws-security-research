from typing import Dict, List

from aws_cdk import Duration, Stack
from aws_cdk.aws_codebuild import (
    Artifacts,
    BuildEnvironment,
    BuildSpec,
    Cache,
    ComputeType,
    LinuxBuildImage,
    LocalCacheMode,
    Project,
    Source,
)
from aws_cdk.aws_events import Rule, Schedule
from aws_cdk.aws_events_targets import CodeBuildProject
from aws_cdk.aws_s3 import LifecycleRule, StorageClass, Transition
from constructs import Construct

from lib.aws_common.s3 import SecureBucket


class MercuryCodeBuild(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.bucket = self.build_artifacts_bucket()
        self.projects = self.build_projects()
        self.rule = self.build_project_rule()

    def build_artifacts_bucket(self) -> SecureBucket:
        return SecureBucket(
            self,
            bucket_id="MercuryArtifactBucket",
            bucket_name="mercury-codebuild-artifacts",
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
            targets=[CodeBuildProject(proj) for proj in self.projects],
        )

    def build_projects(self) -> List[Project]:
        environments: Dict[str, LinuxBuildImage] = {
            "x86": LinuxBuildImage.AMAZON_LINUX_2_4,
            "arm": LinuxBuildImage.AMAZON_LINUX_2_ARM_2,
        }

        projects = []
        for arch, image in environments.items():
            proj = Project(
                self,
                f"MercuryProject{arch.capitalize()}",
                build_spec=self.build_spec,
                source=self.source,
                concurrent_build_limit=1,
                environment=BuildEnvironment(build_image=image, compute_type=ComputeType.SMALL),
                project_name=f"mercury-codebuild-{arch}",
                cache=Cache.local(LocalCacheMode.SOURCE),
                artifacts=Artifacts.s3(
                    bucket=self.bucket,
                    include_build_id=False,
                    package_zip=False,
                ),
            )
            projects.append(proj)
        return projects

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
