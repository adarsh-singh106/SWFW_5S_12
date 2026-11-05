#!/usr/bin/env bash
# Step 01: Start all four GCE Virtual Machines and poll until RUNNING.
# Default mode is --dry-run. Live cloud mutation requires --execute.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=00-config.env
source "${SCRIPT_DIR}/00-config.env"

EXECUTE=false
for arg in "$@"; do
  case "$arg" in
    --execute)
      EXECUTE=true
      shift
      ;;
    --dry-run)
      EXECUTE=false
      shift
      ;;
    -h|--help)
      echo "Usage: $0 [--dry-run | --execute]"
      echo "  --dry-run  (Default) Print commands without executing live cloud changes."
      echo "  --execute  Execute live instance startup in GCP."
      exit 0
      ;;
  esac
done

VMS=("${CONTROLLER_VM}" "${NODE_A_VM}" "${NODE_B_VM}" "${NODE_C_VM}")

echo "============================================================"
echo "GCE Deployment - Step 01: Start Fleet VMs"
echo "Project: ${GCP_PROJECT}"
echo "Zone:    ${GCP_ZONE}"
echo "Target VMs: ${VMS[*]}"
echo "============================================================"

if [ "${EXECUTE}" != "true" ]; then
  echo "[DRY-RUN] Live execution skipped. To execute against GCE, pass --execute."
  echo "[DRY-RUN] Would run:"
  echo "  gcloud compute instances start ${VMS[*]} \\"
  echo "    --project=\"${GCP_PROJECT}\" \\"
  echo "    --zone=\"${GCP_ZONE}\""
  echo "[DRY-RUN] Would poll status until all instances report 'RUNNING'."
  exit 0
fi

echo "[*] Live execution confirmed. Starting instances..."
gcloud compute instances start "${VMS[@]}" \
  --project="${GCP_PROJECT}" \
  --zone="${GCP_ZONE}"

echo "[*] Polling instance status until all 4 nodes report RUNNING..."
MAX_ATTEMPTS=30
SLEEP_INTERVAL=5

for vm in "${VMS[@]}"; do
  attempt=1
  while true; do
    status=$(gcloud compute instances describe "${vm}" \
      --project="${GCP_PROJECT}" \
      --zone="${GCP_ZONE}" \
      --format="value(status)" 2>/dev/null || echo "UNKNOWN")
    
    if [ "${status}" = "RUNNING" ]; then
      echo "  [OK] ${vm} is RUNNING."
      break
    fi

    if [ "${attempt}" -ge "${MAX_ATTEMPTS}" ]; then
      echo "  [ERROR] Timed out waiting for ${vm} to become RUNNING (current: ${status})." >&2
      exit 1
    fi

    echo "  [WAIT] ${vm} is currently ${status} (attempt ${attempt}/${MAX_ATTEMPTS})..."
    attempt=$((attempt + 1))
    sleep "${SLEEP_INTERVAL}"
  done
done

echo "[SUCCESS] All four instances are RUNNING."
