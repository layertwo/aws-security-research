from functools import cached_property

import aws_cdk.aws_kinesisfirehose_alpha as firehose
import aws_cdk.aws_kinesisfirehose_destinations_alpha as destinations
from aws_cdk import Duration, Stack
from aws_cdk import aws_autoscaling as autoscaling
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3deploy
from constructs import Construct

from lib.aws_common.ec2 import build_security_group
from lib.aws_common.s3 import build_bucket


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
    def vpc(self) -> ec2.Vpc:
        return ec2.Vpc(
            self,
            f"{self.name}Vpc",
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                )
            ],
            max_azs=3,
        )

    @property
    def cw_metric_write_statement(self) -> iam.PolicyStatement:
        """CloudWatch metric write statement for ec2 instance"""
        return iam.PolicyStatement(
            actions=["cloudwatch:PutMetricData", "cloudwatch:ListMetrics"], resources=["*"]
        )

    def build_asg(self) -> autoscaling.AutoScalingGroup:
        asg = autoscaling.AutoScalingGroup(
            self,
            f"{self.name}AutoScalingGroup",
            instance_type=ec2.InstanceType("t4g.small"),
            machine_image=self.mercury_machine_image,
            min_capacity=1,
            max_capacity=2,
            vpc=self.vpc,
            cooldown=Duration.seconds(30),
            instance_monitoring=autoscaling.Monitoring.BASIC,
            max_instance_lifetime=Duration.days(1),
            update_policy=autoscaling.UpdatePolicy.replacing_update(),
            security_group=self.sensor_security_group,
            # set a spot price to keep costs low
            spot_price="0.007",
        )
        asg.add_to_role_policy(self.cw_metric_write_statement)
        return asg

    @property
    def mercury_machine_image(self) -> ec2.MachineImage:
        return ec2.MachineImage.latest_amazon_linux(
            generation=ec2.AmazonLinuxGeneration.AMAZON_LINUX_2,
            cpu_type=ec2.AmazonLinuxCpuType.ARM_64,
            kernel=ec2.AmazonLinuxKernel.KERNEL5_X,
            user_data=self.mercury_user_data,
        )

    @property
    def mercury_user_data(self) -> ec2.UserData:
        script_name = "mercury_sensor_setup.sh"
        user_data = ec2.UserData.for_linux()
        user_data.add_commands(
            f'export REGION="{self.region.lower()}"',
            f'export FIREHOSE="{self.firehose.delivery_stream_name}"',
            f"aws s3 cp {self.installables_bucket.s3_url_for_object(key=script_name)} /tmp/{script_name}",
            f"cat /tmp/{script_name} | sh",
        )
        return user_data

    @property
    def sensor_security_group(self) -> ec2.SecurityGroup:
        sg = build_security_group(self, vpc=self.vpc, name=self.name)
        sg.add_ingress_rule(peer=ec2.Peer.any_ipv4(), connection=ec2.Port.all_traffic())
        return sg

    def build_firehose_stream(self) -> firehose.DeliveryStream:
        partition = "year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/"
        stream_id = f"{self.name}SensorStream"
        return firehose.DeliveryStream(
            self,
            stream_id,
            delivery_stream_name=stream_id,
            destinations=[
                destinations.S3Bucket(
                    self.datalake_bucket,
                    compression=destinations.Compression.GZIP,
                    data_output_prefix=f"sensors/{partition}",
                    error_output_prefix=f"sensors-failures/!{{firehose:error-output-type}}/{partition}",
                    buffering_interval=Duration.seconds(300),
                )
            ],
        )

    def build_installables_bucket(self) -> s3.Bucket:
        """Build S3 bucket to store installation files for ec2 instances"""
        bucket = build_bucket(
            self,
            bucket_id=f"{self.name.lower()}-sensor-installables-{self.region.lower()}",
        )
        s3deploy.BucketDeployment(
            self,
            f"{self.name.lower()}SensorInstallableDeployment",
            sources=[s3deploy.Source.asset("./installables/")],
            destination_bucket=bucket,
        )
        return bucket

    def build_datalake_bucket(self) -> s3.Bucket:
        """Build S3 bucket to for sensor datalake"""
        return build_bucket(self, bucket_id=f"{self.name.lower()}-collection-datalake")
