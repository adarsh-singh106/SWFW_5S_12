#!/usr/bin/env bash
# Step 07: Teardown and Cost Optimization: Stop all VMs, verify TERMINATED state, and report storage charges.
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
      echo "  --dry-run  (Default) Print teardown commands and cost summary."
      echo "  --execute  Execute live VM shutdown in GCP."
      exit 0
      ;;
  esac
done

VMS=("${CONTROLLER_VM}" "${NODE_A_VM}" "${NODE_B_VM}" "${NODE_C_VM}")

echo "============================================================"
echo "GCE Teardown & Cost Optimization: Stop Fleet VMs"
echo "Project: ${GCP_PROJECT}"
echo "Zone:    ${GCP_ZONE}"
echo "Target VMs to stop: ${VMS[*]}"
echo "============================================================"

if [ "${EXECUTE}" != "true" ]; then
  echo "[DRY-RUN] Live execution skipped. To stop instances in GCE, pass --execute."
  echo "[DRY-RUN] Would execute:"
  echo "  gcloud compute instances stop ${VMS[*]} \\"
  echo "    --project=\"${GCP_PROJECT}\" \\"
  echo "    --zone=\"${GCP_ZONE}\""
  echo ""
  echo "[DRY-RUN] Would confirm TERMINATED state for all 4 instances."
  echo ""
  echo "=== Cost & Resource Accounting Reminder ==="
  echo "1. VM Compute (vCPU & RAM): Charges stop immediately upon TERMINATED state (\$0.00/hr)."
  echo "2. Persistent Disks (Boot & State): Disks are PRESERVED and NOT deleted."
  echo "   - Controller (${CONTROLLER_VM}): 20 GB balanced persistent disk (pd-balanced)"
  echo "   - Managed Node A (${NODE_A_VM}): 10 GB standard persistent disk (pd-standard)"
  echo "   - Managed Node B (${NODE_B_VM}): 10 GB standard persistent disk (pd-standard)"
  echo "   - Managed Node C (${NODE_C_VM}): 10 GB standard persistent disk (pd-standard)"
  echo "   - Total provisioned storage: 20 GB pd-balanced + 30 GB pd-standard (50 GB total)"
  echo "   - Persistent storage continues to accrue regional GCP disk charges (asia-south1) until deleted."
  echo "3. Firewall Rules & VPC: Preserved intact; no recurring cost for static firewall rules."
  echo "4. Total complete decommissioning (if project is deleted):"
  echo "   gcloud compute instances delete ${VMS[*]} --project=\"${GCP_PROJECT}\" --zone=\"${GCP_ZONE}\" --delete-disks=all"
  exit 0
fi

echo "[*] Live execution confirmed. Stopping all 4 VMs..."
gcloud compute instances stop "${VMS[@]}" \
  --project="${GCP_PROJECT}" \
  --zone="${GCP_ZONE}"

echo "[*] Polling until all 4 instances confirm TERMINATED state..."
MAX_ATTEMPTS=30
SLEEP_INTERVAL=5

for vm in "${VMS[@]}"; do
  attempt=1
  while true; do
    status=$(gcloud compute instances describe "${vm}" \
      --project="${GCP_PROJECT}" \
      --zone="${GCP_ZONE}" \
      --format="value(status)" 2>/dev/null || echo "UNKNOWN")

    if [ "${status}" = "TERMINATED" ]; then
      echo "  [OK] ${vm} is TERMINATED."
      break
    fi

    if [ "${attempt}" -ge "${MAX_ATTEMPTS}" ]; then
      echo "  [ERROR] Timed out waiting for ${vm} to become TERMINATED (current: ${status})." >&2
      exit 1
    fi

    echo "  [WAIT] ${vm} is currently ${status} (attempt ${attempt}/${MAX_ATTEMPTS})..."
    attempt=$((attempt + 1))
    sleep "${SLEEP_INTERVAL}"
  done
done

echo ""
echo "[SUCCESS] All four VMs are verified TERMINATED."
echo "============================================================"
echo "Residual Cost & Resource Accounting Report"
echo "============================================================"
echo "- Compute Charges: \$0.00/hour (All instances TERMINATED)."
echo "- Invariant: Persistent disks preserved intact (data durability guaranteed)."
echo "- Invariant: Firewall rules and IAM roles preserved intact."
echo "- Provisioned Disks Preserved:"
echo "    * Controller (${CONTROLLER_VM}): 20 GB balanced persistent disk (pd-balanced)"
echo "    * Managed Nodes (${NODE_A_VM}, ${NODE_B_VM}, ${NODE_C_VM}): 3 x 10 GB standard persistent disks (pd-standard)"
echo "    * Total: 20 GB pd-balanced + 30 GB pd-standard (50 GB total storage across 4 disks)"
echo "- Ongoing Storage Costs: Standard regional asia-south1 disk rates apply until disks are deleted."
echo "============================================================"
