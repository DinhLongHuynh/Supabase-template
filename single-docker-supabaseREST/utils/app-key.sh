#!/bin/sh
#
# Prints the keys your app needs to reach its tables through the REST API,
# for your app's settings:
#
#   SUPABASE_ANON_KEY  ANON_KEY, which the gateway asks every request for.
#   APP_KEY            A key for the role app, which reaches only the schema
#                      app. Signed with JWT_SECRET, like ANON_KEY and
#                      SERVICE_ROLE_KEY, and valid 5 years.
#
# Usage, after generate-keys.sh:  sh utils/app-key.sh
#
# A new JWT_SECRET invalidates the key: run this again, and update your app.

set -e
cd "$(dirname "$0")/.."

setting() {
    sed -n "s/^$1=//p" .env | tail -n 1
}

jwt_secret=$(setting JWT_SECRET)
anon_key=$(setting ANON_KEY)
if [ -z "$jwt_secret" ] || [ -z "$anon_key" ]; then
    echo "Set JWT_SECRET and ANON_KEY in .env first: sh utils/generate-keys.sh --update-env" >&2
    exit 1
fi

base64_url_encode() {
    openssl enc -base64 -A | tr '+/' '-_' | tr -d '='
}

iat=$(date +%s)
exp=$((iat + 5 * 3600 * 24 * 365))
header=$(printf %s '{"alg":"HS256","typ":"JWT"}' | base64_url_encode)
payload=$(printf %s "{\"role\":\"app\",\"iss\":\"supabase\",\"iat\":$iat,\"exp\":$exp}" | base64_url_encode)
signature=$(printf %s "$header.$payload" | openssl dgst -binary -sha256 -hmac "$jwt_secret" | base64_url_encode)

echo "SUPABASE_ANON_KEY=$anon_key"
echo "APP_KEY=$header.$payload.$signature"
