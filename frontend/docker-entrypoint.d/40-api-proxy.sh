#!/bin/sh
# Generates the same-origin /api reverse proxy when API_UPSTREAM is set:
#   docker compose                  → API_UPSTREAM=http://api:8000
#   Azure without Front Door (dev)  → API_UPSTREAM=https://<api container app fqdn>
# With Front Door, /api/* is routed to the API before it ever reaches this container.
set -eu
mkdir -p /tmp/nginx-extra
rm -f /tmp/nginx-extra/api.conf
[ -n "${API_UPSTREAM:-}" ] || exit 0

# Only scheme://host[:port] is accepted, so nothing can be injected into the nginx config.
if ! printf '%s' "$API_UPSTREAM" | grep -Eq '^https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?$'; then
  echo "40-api-proxy: invalid API_UPSTREAM" >&2
  exit 1
fi
host=$(printf '%s' "$API_UPSTREAM" | sed -E 's#^[a-z]+://##')

# Resolve the upstream per request (not once at start-up) so nginx starts even if the API's DNS name is
# not resolvable yet, and follows address changes. Use the container's own DNS server.
resolver=$(awk '/^nameserver/ { print $2; exit }' /etc/resolv.conf)
case "$resolver" in
  *:*) resolver="[$resolver]" ;;
  "") resolver="127.0.0.11" ;;
esac

cat > /tmp/nginx-extra/api.conf <<CONF
location /api/ {
    resolver ${resolver} valid=30s;
    set \$api_upstream ${API_UPSTREAM};
    proxy_pass \$api_upstream;
    proxy_http_version 1.1;
    proxy_set_header Host ${host};
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Request-ID \$request_id;
    proxy_ssl_server_name on;
    proxy_ssl_name ${host%%:*};
    proxy_buffering off;
    proxy_read_timeout 300s;
    client_max_body_size 32k;
}
CONF
echo "40-api-proxy: /api -> ${API_UPSTREAM} (resolver ${resolver})"
