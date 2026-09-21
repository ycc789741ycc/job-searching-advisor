#!/bin/sh
# Writes the SPA's runtime configuration from the environment.
#
# These are public values by definition — they reach the browser. A secret must
# never appear here; anything sensitive goes through the API instead.
set -eu

: "${WEB_API_BASE_URL:?WEB_API_BASE_URL is required}"

cat > /usr/share/nginx/html/config.js <<JS
window.__APP_CONFIG__ = {
  apiBaseUrl: "${WEB_API_BASE_URL}"
};
JS

echo "wrote config.js for ${WEB_API_BASE_URL}"
