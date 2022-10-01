#!/bin/bash
sudo yum --assumeyes update
sudo yum --assumeyes install git gcc10 gcc10-c++ zlib-devel openssl-devel kernel-devel autoconf libasan10

# setup and install mercury
git clone https://github.com/cisco/mercury --depth 1 /tmp/mercury
cd /tmp/mercury
./configure CC=/usr/bin/gcc10-gcc CPP=/usr/bin/gcc10-cpp CXX=/usr/bin/gcc10-c++
sudo make install MERCURY_CFG=mercury.cfg CC=/usr/bin/gcc10-gcc CPP=/usr/bin/gcc10-cpp CXX=/usr/bin/gcc10-c++ V=s
sudo setcap cap_net_raw,cap_net_admin,cap_dac_override+eip /usr/local/bin/mercury

# mercury configuration
sed -i 's/ens33/eth0/g' /etc/mercury/mercury.cfg
sed -i 's/cpu/1/g' /etc/mercury/mercury.cfg

# install fluent-bit
curl https://raw.githubusercontent.com/fluent/fluent-bit/master/install.sh | sh
sudo yum --assumeyes install fluent-bit

cat > /etc/fluent-bit/fluent-bit.conf << EOL
[INPUT]
    Name tail
    tag mercury.data
    Path /usr/local/var/mercury/fingerprint.json*
    Parser json

[OUTPUT]
    Name  kinesis_firehose
    Match mercury.*
    region $REGION
    delivery_stream $FIREHOSE
EOL

cat > /etc/fluent-bit/parsers.conf << EOL
[PARSER]
    Name   json
    Format json
    Time_Key event_start
    Time_Format %s.%6"
EOL

# sleep before starting services
sleep 5
sudo systemctl start mercury
sudo systemctl enable mercury
sudo systemctl start fluent-bit
sudo systemctl enable fluent-bit
