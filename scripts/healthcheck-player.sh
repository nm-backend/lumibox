#!/bin/bash
# Healthcheck плеера LumiBox — тонкая обёртка над unittest-ом.
#
# Вся логика теперь в Python:
#   apps/streaming/test_selenium.py :: PlayerHealthcheckTest
#
# Зависимости:
#   - Chrome / Chromium
#   - Python 3.13+ с установленными зависимостями проекта
#
# Использование:
#   bash scripts/healthcheck-player.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass() { echo -e "${GREEN}✓${NC} $1"; }
fail() { echo -e "${RED}✗${NC} $1"; }
info() { echo -e "${YELLOW}→${NC} $1"; }

cd "$PROJECT_DIR"

export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings.development}"

info "Запуск healthcheck плеера (StaticLiveServerTestCase + Selenium)..."

if python -m django test apps.streaming.test_selenium \
    --settings="${DJANGO_SETTINGS_MODULE}" \
    --tag=selenium -v 2 2>&1; then
    echo ""
    pass "Healthcheck плеера успешно пройден"
    exit 0
else
    echo ""
    fail "Healthcheck плеера не пройден"
    exit 1
fi
