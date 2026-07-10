FROM node:22-bookworm

ARG TZ=UTC
ENV TZ=$TZ

RUN apt-get update && apt-get install -y --no-install-recommends \
      less \
      git \
      procps \
      sudo \
      fzf \
      zsh \
      man-db \
      unzip \
      gnupg2 \
      ca-certificates \
      iptables \
      ipset \
      iproute2 \
      dnsutils \
      aggregate \
      jq \
      curl \
      nano \
      sqlite3 \
  && rm -rf /var/lib/apt/lists/*

# Playwright browser + OS deps, pinned to a known-good version, in a shared path
# readable by the node user. Done at build time (as root) so container runtime
# never needs network access to fetch the browser through the egress firewall.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
RUN npx --yes playwright@1.56.0 install --with-deps chromium \
  && rm -rf /var/lib/apt/lists/*

# Persist bash history across rebuilds via named volume.
RUN mkdir -p /commandhistory \
  && touch /commandhistory/.bash_history \
  && chown -R node:node /commandhistory

ENV DEVCONTAINER=true

# Allow the default `node` user to run the firewall script (and only that) without a password.
RUN echo 'node ALL=(root) NOPASSWD: /usr/local/bin/init-firewall.sh' > /etc/sudoers.d/node-firewall \
  && chmod 0440 /etc/sudoers.d/node-firewall

COPY init-firewall.sh /usr/local/bin/init-firewall.sh
RUN chmod 0755 /usr/local/bin/init-firewall.sh \
  && chown root:root /usr/local/bin/init-firewall.sh

USER node

# Global npm dir owned by `node` so Claude Code installs without sudo.
ENV NPM_CONFIG_PREFIX=/home/node/.npm-global
ENV PATH=$PATH:/home/node/.npm-global/bin
RUN mkdir -p /home/node/.npm-global \
  && npm install -g @anthropic-ai/claude-code

WORKDIR /workspace
