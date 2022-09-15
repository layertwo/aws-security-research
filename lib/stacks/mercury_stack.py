from aws_cdk import Stack, Duration
from aws_cdk import aws_autoscaling as autoscaling
from aws_cdk import aws_ec2 as ec2
from constructs import Construct


class MercuryStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # setup VPC
        self.vpc = ec2.Vpc(
            self,
            "MercuryVpc",
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                )
            ],
            max_azs=3,
        )

        asg = autoscaling.AutoScalingGroup(
            self,
            "MercuryScalingGroup",
            instance_type=ec2.InstanceType("t4g.small"),
            machine_image=self.mercury_machine_image,
            min_capacity=2,
            max_capacity=3,
            vpc=self.vpc,
            instance_monitoring=autoscaling.Monitoring.BASIC,
            max_instance_lifetime=Duration.days(1),
            update_policy=autoscaling.UpdatePolicy.replacing_update(),
        )

    @property
    def mercury_machine_image(self) -> ec2.MachineImage:
        return ec2.MachineImage.latest_amazon_linux(
            generation=ec2.AmazonLinuxGeneration.AMAZON_LINUX_2,
            kernel=ec2.AmazonLinuxKernel.KERNEL5_X,
        )
