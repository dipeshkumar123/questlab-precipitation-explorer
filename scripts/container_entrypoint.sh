#!/bin/sh
set -eu
envsubst '${PORT}' < /app/deploy/nginx.conf.template > /etc/nginx/conf.d/default.conf
exec supervisord -c /app/deploy/supervisord.conf
