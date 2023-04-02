from functools import cached_property

from aws_cdk import Duration, Stack
from aws_cdk.aws_autoscaling import AutoScalingGroup, Monitoring, Signals, UpdatePolicy
from aws_cdk.aws_ec2 import (
    AmazonLinuxCpuType,
    AmazonLinuxGeneration,
    AmazonLinuxKernel,
    CloudFormationInit,
    InitCommand,
    InitFile,
    InitService,
    InstanceType,
    LaunchTemplate,
    LaunchTemplateSpotOptions,
    MachineImage,
    Peer,
    Port,
    SecurityGroup,
    SubnetConfiguration,
    SubnetType,
    UserData,
    Vpc,
)
from aws_cdk.aws_iam import PolicyStatement, Role, ServicePrincipal
from aws_cdk.aws_kinesisfirehose_alpha import DeliveryStream
from aws_cdk.aws_kinesisfirehose_destinations_alpha import Compression, S3Bucket
from aws_cdk.aws_s3 import Bucket
from constructs import Construct

from lib.aws_common.ec2 import build_security_group
from lib.aws_common.s3 import SecureBucket


class MercuryStack(Stack):
    def __init__(
        self, scope: Construct, construct_id: str, artifacts_bucket: SecureBucket, **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self.name = "Mercury"

        self.instance_role = self.build_instance_role()
        # build s3 buckets
        self.datalake_bucket = self.build_datalake_bucket()
        self.artifacts_bucket = artifacts_bucket

        # build firehose
        self.firehose = self.build_firehose_stream()

        # build autoscaling group
        self.asg = self.build_asg()
        artifacts_bucket.grant_read(self.instance_role)
        self.firehose.grant_put_records(self.instance_role)

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
            min_capacity=1,
            max_capacity=2,
            vpc=self.vpc,
            launch_template=self.launch_template,
            cooldown=Duration.seconds(30),
            instance_monitoring=Monitoring.BASIC,
            max_instance_lifetime=Duration.days(1),
            update_policy=UpdatePolicy.rolling_update(min_success_percentage=0),
            init=self.instance_init_config,
            signals=Signals.wait_for_all(timeout=Duration.minutes(15)),
        )
        asg.add_to_role_policy(self.cw_metric_write_statement)
        return asg

    @property
    def launch_template(self) -> LaunchTemplate:
        return LaunchTemplate(
            self,
            f"{self.name}LaunchTemplate",
            machine_image=self.mercury_machine_image,
            instance_type=InstanceType("t4g.micro"),
            security_group=self.sensor_security_group,
            detailed_monitoring=False,
            spot_options=LaunchTemplateSpotOptions(max_price=0.007),
            role=self.instance_role,
            user_data=UserData.for_linux(),
        )

    def build_instance_role(self) -> Role:
        name = f"{self.name}InstanceRole"
        return Role(
            self,
            name,
            role_name=name,
            assumed_by=ServicePrincipal("ec2.amazonaws.com"),
        )

    @property
    def mercury_machine_image(self) -> MachineImage:
        return MachineImage.latest_amazon_linux(
            generation=AmazonLinuxGeneration.AMAZON_LINUX_2,
            cpu_type=AmazonLinuxCpuType.ARM_64,
            kernel=AmazonLinuxKernel.KERNEL5_X,
        )

    @property
    def instance_init_config(self) -> CloudFormationInit:
        rpm_name = "mercury-2.5.16-1.el7.aarch64.rpm"
        rpm_path = f"mercury-package/{rpm_name}"
        return CloudFormationInit.from_elements(
            InitCommand.shell_command(
                "curl https://raw.githubusercontent.com/fluent/fluent-bit/master/install.sh | sh"
            ),
            InitCommand.shell_command("yum update -y"),
            InitCommand.shell_command("yum install htop fluent-bit -y"),
            InitCommand.shell_command(
                f"aws s3 cp {self.artifacts_bucket.s3_url_for_object(key=rpm_path)} /tmp/{rpm_name}"
            ),
            InitCommand.shell_command(f"rpm -i /tmp/{rpm_name}"),
            InitCommand.shell_command("sed -i 's/ens33/eth0/g' /etc/mercury/mercury.cfg"),
            InitCommand.shell_command("sed -i 's/cpu/1/g' /etc/mercury/mercury.cfg"),
            InitFile.from_string("/etc/fluent-bit/fluent-bit.conf", self.fluent_bit_config),
            InitFile.from_string("/etc/fluent-bit/parsers.conf", self.fluent_bit_parser),
            InitService.enable("fluent-bit", enabled=True),
            InitService.enable("mercury", enabled=True),
        )

    @property
    def fluent_bit_config(self) -> str:
        # /etc/fluent-bit/fluent-bit.conf << EOL
        return f"""
        [INPUT]
            Name tail
            tag mercury.data
            Path /usr/local/var/mercury/fingerprint.json*
            Parser json

        [OUTPUT]
            Name  kinesis_firehose
            Match mercury.*
            region {self.region}
            delivery_stream {self.firehose.delivery_stream_name}
        """

    @property
    def fluent_bit_parser(self) -> str:
        # /etc/fluent-bit/parsers.conf
        return """[PARSER]
            Name   json
            Format json
            Time_Key event_start
            Time_Format %s.%6"
        """

    @cached_property
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

    def build_datalake_bucket(self) -> Bucket:
        """Build S3 bucket to for sensor datalake"""
        return SecureBucket(self, bucket_id=f"{self.name.lower()}-collection-datalake")
