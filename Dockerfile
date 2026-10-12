# syntax=docker/dockerfile:1

FROM debian:bookworm-slim

# Архитектура сборки. buildx (Railway использует именно его) проставляет
# TARGETARCH автоматически; для локальной сборки задаётся значением по умолчанию.
ARG TARGETARCH=amd64

# Сегмент пути в API релизов opencode: latest или конкретная версия (например v2.0.12).
ARG OPENCODE_CHANNEL=latest
ARG TTYD_VERSION=1.7.7

ENV DEBIAN_FRONTEND=noninteractive \
    TERM=xterm-256color \
    OPENCODE_DISABLE_AUTOUPDATE=1

# ca-certificates — TLS к провайдерам и GitHub
# git             — opencode работает с репозиториями
# ripgrep         — встроенный поиск по файлам
# tini            — корректная обработка сигналов (иначе SIGTERM не доходит до opencode)
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      git \
      ripgrep \
      tini \
 && rm -rf /var/lib/apt/lists/*

# ttyd — веб-терминал. В bookworm его нет (только sid/forky), поэтому статическая сборка.
RUN set -eux; \
    case "$TARGETARCH" in \
      amd64)  TTYD_ARCH=x86_64 ;; \
      arm64)  TTYD_ARCH=aarch64 ;; \
      *) echo "unsupported TARGETARCH: $TARGETARCH" >&2; exit 1 ;; \
    esac; \
    curl -fsSL "https://github.com/tsl0922/ttyd/releases/download/${TTYD_VERSION}/ttyd.${TTYD_ARCH}" \
      -o /usr/local/bin/ttyd; \
    chmod 0755 /usr/local/bin/ttyd

# opencode CLI v2 — официальный standalone-бинарь под нужную архитектуру.
RUN set -eux; \
    case "$TARGETARCH" in \
      amd64)  OC_ARCH=x64 ;; \
      arm64)  OC_ARCH=arm64 ;; \
      *) echo "unsupported TARGETARCH: $TARGETARCH" >&2; exit 1 ;; \
    esac; \
    curl -fsSL "https://opencode.ai/update/api/${OPENCODE_CHANNEL}/cli/opencode/opencode-linux-${OC_ARCH}.tar.gz" \
      -o /tmp/opencode.tar.gz; \
    tar -xzf /tmp/opencode.tar.gz -C /usr/local/bin opencode; \
    chmod 0755 /usr/local/bin/opencode; \
    rm -f /tmp/opencode.tar.gz; \
    opencode --version

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
# Страховка: если entrypoint.sh когда-то попадёт в репозиторий с CRLF,
# /bin/sh споткнётся на \r и контейнер не стартует.
RUN chmod 0755 /usr/local/bin/entrypoint.sh \
 && sed -i 's/\r$//' /usr/local/bin/entrypoint.sh

# Здесь живёт проект и все сессии opencode. Сюда же монтируется Railway Volume.
WORKDIR /workspace

ENV PORT=8080
EXPOSE 8080

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint.sh"]