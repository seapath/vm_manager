FROM ubuntu:22.04

ENV DEBIAN_FRONTEND noninteractive
RUN set -x \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        black \
        pylint \
        python3 \
        python3-flake8 \
        python3-setuptools \
        openjdk-8-jre-headless \
        unzip \
        wget \
    && rm -rf /var/lib/apt/lists/

ARG sonar_version=4.7.0.2747
ARG sonar_repo=https://binaries.sonarsource.com/Distribution/sonar-scanner-cli
RUN set -x \
    && wget -O /tmp/sonar-scanner.zip \
    "${sonar_repo}/sonar-scanner-cli-${sonar_version}.zip" \
    && cd /opt \
    && unzip /tmp/sonar-scanner.zip \
    && rm -f sonar-scanner.zip
RUN ln -s "/opt/sonar-scanner-${sonar_version}" /opt/sonar-scanner
RUN echo 'sonar.host.url=http://j1.sfl.team:9000/' \
    > /opt/sonar-scanner/conf/sonar-scanner.properties
COPY python-sonar.sh /usr/bin/python-sonar.sh
