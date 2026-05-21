#!/usr/bin/env sh
set -eu

API_BASE_URL="${API_BASE_URL:-http://localhost:8000}"

# Escape for JSON string (prevent injection)
API_BASE_URL_ESC=$(printf '%s' "$API_BASE_URL" | sed 's/\\/\\\\/g; s/"/\\"/g; s/\n/\\n/g; s/\r/\\r/g; s/\t/\\t/g')

cat > /usr/share/nginx/html/runtime-config.js <<EOF
window.__AGENT33_CONFIG__ = {
  API_BASE_URL: "${API_BASE_URL_ESC}"
};
EOF
