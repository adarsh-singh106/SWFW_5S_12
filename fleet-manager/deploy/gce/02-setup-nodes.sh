#!/usr/bin/env bash
# Step 02: Install and configure Prometheus Node Exporter on managed nodes A, B, and C.
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
      echo "  --dry-run  (Default) Print commands without executing live changes."
      echo "  --execute  Execute live node configuration via IAP SSH."
      exit 0
      ;;
  esac
done

NODES=("${NODE_A_VM}" "${NODE_B_VM}" "${NODE_C_VM}")

echo "============================================================"
echo "GCE Deployment - Step 02: Provision Node Exporters"
echo "Target Nodes: ${NODES[*]}"
echo "Firewall: Port 9100 permitted internally via VPC rule 'default-allow-internal' (10.128.0.0/9)"
echo "============================================================"

NODE_SETUP_COMMAND="sudo apt-get update && sudo apt-get install -y prometheus-node-exporter && sudo systemctl enable --now prometheus-node-exporter && sudo ss -tlpn | grep 9100"

if [ "${EXECUTE}" != "true" ]; then
  echo "[DRY-RUN] Live execution skipped. To execute, pass --execute."
  for node in "${NODES[@]}"; do
    echo "[DRY-RUN] Would run on ${node} via IAP:"
    echo "  gcloud compute ssh ${node} \\"
    echo "    --project=\"${GCP_PROJECT}\" \\"
    echo "    --zone=\"${GCP_ZONE}\" \\"
    echo "    --tunnel-through-iap \\"
    echo "    --command=\"${NODE_SETUP_COMMAND}\""
  done
  exit 0
fi

echo "[*] Live execution confirmed. Provisioning Node Exporter across managed nodes..."

for node in "${NODES[@]}"; do
  echo "[*] Configuring ${node}..."
  gcloud compute ssh "${node}" \
    --project="${GCP_PROJECT}" \
    --zone="${GCP_ZONE}" \
    --tunnel-through-iap \
    --command="${NODE_SETUP_COMMAND}"
  echo "  [OK] ${node} node-exporter active."
done

echo "[SUCCESS] Node Exporter successfully installed and running on all managed nodes."
