FROM ubuntu:20.04

ENV DEBIAN_FRONTEND noninteractive
RUN    set -x \
    && apt update \
    && apt install -y --no-install-recommends \
        build-essential \
        python3 \
        python3-setuptools \
        python3-pip \
        pylint3 \
        openjdk-8-jre-headless \
        wget \
        unzip

RUN wget -O /tmp/sonar-scanner.zip "https://github.com/SonarSource/sonar-scanner-cli/releases/download/4.4.0.2170/sonar-scanner-cli-4.4.0.2170-linux.zip" && \
    ( cd /opt; unzip /tmp/sonar-scanner.zip )
RUN ln -s /opt/sonar-scanner-4.4.0.2170-linux /opt/sonar-scanner
RUN echo 'sonar.host.url=http://j1.sfl.team:9000/' > /opt/sonar-scanner/conf/sonar-scanner.properties
ADD python-sonar.sh /usr/bin/python-sonar.sh
RUN python3 -m pip install black flake8
