from functools import cached_property

from aws_cdk import Duration, Stack
from aws_cdk.aws_autoscaling import AutoScalingGroup, Monitoring, UpdatePolicy
from aws_cdk.aws_ec2 import (
    AmazonLinuxCpuType,
    AmazonLinuxGeneration,
    AmazonLinuxKernel,
    InstanceType,
    MachineImage,
    Peer,
    Port,
    SecurityGroup,
    SubnetConfiguration,
    SubnetType,
    UserData,
    Vpc,
)
from aws_cdk.aws_iam import PolicyStatement
from aws_cdk.aws_kinesisfirehose_alpha import DeliveryStream
from aws_cdk.aws_kinesisfirehose_destinations_alpha import Compression, S3Bucket
from aws_cdk.aws_s3 import Bucket
from aws_cdk.aws_s3_deployment import BucketDeployment, Source
from constructs import Construct

from lib.aws_common.ec2 import build_security_group
from lib.aws_common.s3 import SecureBucket


class MercuryStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self.name = "Mercury"

        # build s3 buckets
        self.installables_bucket = self.build_installables_bucket()
        self.datalake_bucket = self.build_datalake_bucket()

        # build firehose
        self.firehose = self.build_firehose_stream()

        # build autoscaling group
        self.asg = self.build_asg()
        self.installables_bucket.grant_read(self.asg)
        self.firehose.grant_put_records(self.asg)

    @cached_property
    def vpc(self) -> Vpc:
        return Vpc(
            self,
            f"{self.name}Vpc",
            subnet_configuration=[
                SubnetConfiguration(
                    name="Public",
                    subnet_type=SubnetType.PUBLIC,
                    cidr_mask=24,
                )
            ],
            max_azs=3,
        )

    @property
    def cw_metric_write_statement(self) -> PolicyStatement:
        """CloudWatch metric write statement for ec2 instance"""
        return PolicyStatement(
            actions=["cloudwatch:PutMetricData", "cloudwatch:ListMetrics"], resources=["*"]
        )

    def build_asg(self) -> AutoScalingGroup:
        asg = AutoScalingGroup(
            self,
            f"{self.name}AutoScalingGroup",
            instance_type=InstanceType("t4g.small"),
            machine_image=self.mercury_machine_image,
            min_capacity=1,
            max_capacity=2,
            vpc=self.vpc,
            cooldown=Duration.seconds(30),
            instance_monitoring=Monitoring.BASIC,
            max_instance_lifetime=Duration.days(1),
            update_policy=UpdatePolicy.replacing_update(),
            security_group=self.sensor_security_group,
            # set a spot price to keep costs low
            spot_price="0.007",
        )
        asg.add_to_role_policy(self.cw_metric_write_statement)
        return asg

    @property
    def mercury_machine_image(self) -> MachineImage:
        return MachineImage.latest_amazon_linux(
            generation=AmazonLinuxGeneration.AMAZON_LINUX_2,
            cpu_type=AmazonLinuxCpuType.ARM_64,
            kernel=AmazonLinuxKernel.KERNEL5_X,
            user_data=self.mercury_user_data,
        )

    @property
    def mercury_user_data(self) -> UserData:
        script_name = "mercury_sensor_setup.sh"
        user_data = UserData.for_linux()
        user_data.add_commands(
            f'export REGION="{self.region}"',
            f'export FIREHOSE="{self.firehose.delivery_stream_name}"',
            f"aws s3 cp {self.installables_bucket.s3_url_for_object(key=script_name)} /tmp/{script_name}",
            f"cat /tmp/{script_name} | sh",
        )
        return user_data

    @property
    def sensor_security_group(self) -> SecurityGroup:
        sg = build_security_group(self, vpc=self.vpc, name=self.name)
        sg.add_ingress_rule(peer=Peer.any_ipv4(), connection=Port.all_traffic())
        return sg

    def build_firehose_stream(self) -> DeliveryStream:
        partition = "year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/"
        stream_id = f"{self.name}SensorStream"
        return DeliveryStream(
            self,
            stream_id,
            delivery_stream_name=stream_id,
            destinations=[
                S3Bucket(
                    self.datalake_bucket,
                    compression=Compression.GZIP,
                    data_output_prefix=f"sensors/{partition}",
                    error_output_prefix=f"sensors-failures/!{{firehose:error-output-type}}/{partition}",
                    buffering_interval=Duration.seconds(300),
                )
            ],
        )

    def build_installables_bucket(self) -> Bucket:
        """Build S3 bucket to store installation files for ec2 instances"""
        bucket = SecureBucket(
            self,
            bucket_id=f"{self.name.lower()}-sensor-installables-{self.region}",
        )
        BucketDeployment(
            self,
            f"{self.name.lower()}SensorInstallableDeployment",
            sources=[Source.asset("./installables/")],
            destination_bucket=bucket,
        )
        return bucket

    def build_datalake_bucket(self) -> Bucket:
        """Build S3 bucket to for sensor datalake"""
        return SecureBucket(self, bucket_id=f"{self.name.lower()}-collection-datalake")
