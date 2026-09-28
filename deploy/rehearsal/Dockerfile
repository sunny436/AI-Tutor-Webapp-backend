# A throwaway stand-in for the production host, for `bun run rehearse`. Never used in production.
# Ubuntu 24.04 with real systemd (the deploy scripts rely on systemd-run, cgroups and the
# journal), PostgreSQL 16 + pgvector running natively (production runs it in Docker; a stub
# `docker` below starts the native one), SSH for deploy/deploy.sh, and the rehearsal marker that
# lets DEPLOY_REHEARSAL=1 deploy here and nowhere else.
FROM ubuntu:24.04
ARG BUN_VERSION
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends systemd systemd-sysv dbus curl ca-certificates \
      unzip xz-utils git python3.12 python3.12-venv postgresql-16 postgresql-16-pgvector iproute2 openssh-server \
    && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL https://bun.sh/install | BUN_INSTALL=/root/.bun bash -s "bun-v${BUN_VERSION}"
COPY docker-stub /usr/bin/docker
COPY docker.service /etc/systemd/system/docker.service
COPY authorized_keys /root/.ssh/authorized_keys
RUN chmod 755 /usr/bin/docker && chmod 700 /root/.ssh && chmod 600 /root/.ssh/authorized_keys \
    && mkdir -p /etc/aichat && touch /etc/aichat/REHEARSAL \
    && systemctl enable ssh postgresql docker \
    && sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
