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
        python3-sphinx \
        python3-pip \
    && rm -rf /var/lib/apt/lists/ \
    # Pinned so a rebuild does not pick up a new release on its own, and
    # restricted to wheels so no dependency gets to run a setup script
    # during the install. 0.6.0 is what the unpinned line already
    # resolved to on the python3.10 of ubuntu 22.04.
    && pip3 install --no-cache-dir --only-binary :all: \
        sphinx-argparse==0.6.0
