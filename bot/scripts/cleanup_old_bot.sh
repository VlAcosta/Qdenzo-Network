#!/usr/bin/env bash
set -euo pipefail

# This script tries to remove old bot containers from previous deployments.
# It is SAFE for Marzban containers, but ALWAYS read what it will remove.

PATTERNS=("smartvpn-bot" "qdenzo-network" "qdenzo_bot" "qdenzo-bot")

echo "== Containers matching patterns =="
for p in "${PATTERNS[@]}"; do
  docker ps -a --format '{{.Names}}' | grep -E "^${p}" || true
done

echo
read -r -p "Stop & remove these containers? (y/N) " ans
if [[ "${ans}" != "y" && "${ans}" != "Y" ]]; then
  echo "Aborted."
  exit 0
fi

for p in "${PATTERNS[@]}"; do
  ids=$(docker ps -a --filter "name=^${p}" -q || true)
  if [[ -n "${ids}" ]]; then
    docker rm -f ${ids}
  fi
done

echo "Done."
