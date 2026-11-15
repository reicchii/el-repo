#!/bin/bash
# Shows which of the project's hosts this machine can reach.
#
#   bash scripts/check-network.sh               probe every host, then run the archive check
#   bash scripts/check-network.sh --allowlist   print the hosts a cloud environment must allow
#
# Hosts and their purpose are listed in scripts/hosts.txt.
# Exit code 0 means the IRSA archive answered a real query. Without it no lane can work.

set -u
cd "$(dirname "$0")" || exit 1

hosts() { grep -vE '^[[:space:]]*(#|$)' hosts.txt; }

if [ "${1:-}" = "--allowlist" ]; then
  hosts | awk '$1 == "allow" { print $2 }'
  exit 0
fi

echo "Hosts"
while read -r _kind host what; do
  code=$(curl -s -o /dev/null -m 15 -w '%{http_code}' "https://$host/" 2>/dev/null)
  if [ "$code" = "000" ]; then
    state="NO ANSWER"
  else
    state="reached"
  fi
  printf '  %-10s %-46s %s\n' "$state" "$host" "$what"
done < <(hosts)

echo
echo "Archive check: three table names from IRSA TAP"
answer=$(curl -s -m 60 "https://irsa.ipac.caltech.edu/TAP/sync?QUERY=SELECT+TOP+3+table_name+FROM+TAP_SCHEMA.tables&FORMAT=CSV")
while IFS= read -r line; do echo "  $line"; done <<< "$answer"
if [ "$(echo "$answer" | grep -c .)" -ge 4 ] && echo "$answer" | head -n 1 | grep -q '^table_name'; then
  echo "Archive reachable."
  exit 0
fi
echo "Archive NOT reachable from this machine. See SETUP.md section 8."
exit 1
