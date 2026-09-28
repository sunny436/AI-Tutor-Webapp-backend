# The runner of `bun run verify` (deploy/verify.mjs): Ubuntu 24.04 like CI's ubuntu-latest,
# Python 3.12 like CI's setup-python, and the Node and Bun that the commit being verified pins
# (.node-version, .bun-version), each checked against its release's published SHA-256.
FROM ubuntu:24.04@sha256:008173c23f95b170204355c12626cb5a965d779a7e1283b09e9cffbb1bf33ca3

ARG NODE_VERSION
ARG BUN_VERSION
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
  && apt-get install -y --no-install-recommends python3.12 python3.12-venv ca-certificates curl git unzip xz-utils \
  && rm -rf /var/lib/apt/lists/* \
  && ln -s /usr/bin/python3.12 /usr/local/bin/python

RUN set -e; test -n "$NODE_VERSION"; cd /tmp; f="node-v$NODE_VERSION-linux-x64.tar.xz"; \
  curl -fsSLO "https://nodejs.org/dist/v$NODE_VERSION/$f"; \
  curl -fsSL "https://nodejs.org/dist/v$NODE_VERSION/SHASUMS256.txt" | grep " $f\$" | sha256sum -c -; \
  tar -xJf "$f" -C /usr/local --strip-components=1; rm "$f"

RUN set -e; test -n "$BUN_VERSION"; cd /tmp; f=bun-linux-x64.zip; \
  curl -fsSLO "https://github.com/oven-sh/bun/releases/download/bun-v$BUN_VERSION/$f"; \
  curl -fsSL "https://github.com/oven-sh/bun/releases/download/bun-v$BUN_VERSION/SHASUMS256.txt" | grep " $f\$" | sha256sum -c -; \
  unzip -q "$f"; install -m 755 bun-linux-x64/bun /usr/local/bin/bun; ln -s bun /usr/local/bin/bunx; rm -rf "$f" bun-linux-x64

WORKDIR /work
