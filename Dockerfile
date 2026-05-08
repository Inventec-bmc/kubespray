# syntax=docker/dockerfile:1

# Use immutable image tags rather than mutable tags (like ubuntu:22.04)
FROM ubuntu:22.04@sha256:149d67e29f765f4db62aa52161009e99e389544e25a8f43c8c89d4a445a7ca37

# Some tools like yamllint need this
# Pip needs this as well at the moment to install ansible
# (and potentially other packages)
# See: https://github.com/pypa/pip/issues/10219
ENV LANG=C.UTF-8 \
    DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /kubespray

# hadolint ignore=DL3008
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    apt-get update -q \
    && apt-get install -yq --no-install-recommends \
    curl \
    python3 \
    python3-pip \
    sshpass \
    vim \
    rsync \
    openssh-client

RUN apt-get install -yq --no-install-recommends \
    net-tools \
    iputils-ping

RUN apt-get install -yq --no-install-recommends \
    docker.io
    # && apt-get clean \
    # && rm -rf /var/lib/apt/lists/* /var/log/*

RUN --mount=type=bind,source=requirements.txt,target=requirements.txt \
    --mount=type=cache,sharing=locked,id=pipcache,mode=0777,target=/root/.cache/pip \
    pip install --no-compile --no-cache-dir -r requirements.txt \
    && find /usr -type d -name '*__pycache__' -prune -exec rm -rf {} \;

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# 下載 kubectl 以及 kind (強制指定 amd64 架構避免變數解析錯誤)
# RUN OS_ARCHITECTURE=$(dpkg --print-architecture) \
#     && curl -L "https://dl.k8s.io/release/v1.34.3/bin/linux/${OS_ARCHITECTURE}/kubectl" -o /usr/local/bin/kubectl \
#     && echo "$(curl -L "https://dl.k8s.io/release/v1.34.3/bin/linux/${OS_ARCHITECTURE}/kubectl.sha256")" /usr/local/bin/kubectl | sha256sum --check \
#     && chmod a+x /usr/local/bin/kubectl \
#     && curl -Lo /usr/local/bin/kind "https://kind.sigs.k8s.io/dl/v0.22.0/kind-linux-amd64" \
#     && chmod a+x /usr/local/bin/kind

COPY *.yml ./
COPY *.cfg ./
COPY roles ./roles
COPY contrib ./contrib
COPY inventory ./inventory
COPY library ./library
COPY extra_playbooks ./extra_playbooks
COPY playbooks ./playbooks
COPY plugins ./plugins
