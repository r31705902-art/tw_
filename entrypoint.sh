#!/bin/sh
# Точка входа: поднимает ttyd (веб-терминал) с opencode CLI внутри.
set -eu

PORT="${PORT:-8080}"
TTYD_USER="${TTYD_USER:-opencode}"
TTYD_PASSWORD="${TTYD_PASSWORD:-opencode}"
WORKDIR="${WORKDIR:-/workspace}"
MAX_CLIENTS="${MAX_CLIENTS:-5}"

mkdir -p "$WORKDIR"
cd "$WORKDIR"

if [ "$TTYD_PASSWORD" = "opencode" ]; then
    echo "WARNING: TTYD_PASSWORD still has the default value 'opencode'." >&2
    echo "WARNING: Set your own TTYD_PASSWORD in Railway variables, otherwise" >&2
    echo "WARNING: anyone who knows the URL can use your API keys." >&2
fi

echo "opencode-on-railway"
echo "  listening on : 0.0.0.0:${PORT}"
echo "  workdir      : ${WORKDIR}"
echo "  login        : ${TTYD_USER} / ********"
echo "  opencode     : $(opencode --version 2>/dev/null || echo 'unknown')"
echo ""

# После выхода из opencode пользователь получает обычный шелл, а не обрыв консоли.
#
# rendererType=dom обязателен: в ttyd 1.7.7 дефолт — webgl, а Tor Browser блокирует
# и WebGL, и canvas ради защиты от fingerprinting. Без этой опции в Tor Browser
# терминал рисуется мусором и выскакивает запрос разрешения на canvas.
# DOM-рендерер рисует обычными узлами и работает везде, хоть и чуть медленнее.
exec ttyd \
    --port "$PORT" \
    --writable \
    --max-clients "$MAX_CLIENTS" \
    --credential "${TTYD_USER}:${TTYD_PASSWORD}" \
    --cwd "$WORKDIR" \
    --client-option "rendererType=dom" \
    --client-option "titleFixed=opencode" \
    --client-option "fontSize=14" \
    --client-option "fontFamily=Menlo, Monaco, Consolas, monospace" \
    --client-option "scrollback=10000" \
    --client-option "cursorBlink=true" \
    /bin/bash -lc 'opencode; echo; echo "[opencode exited — dropping to shell]"; exec /bin/bash'