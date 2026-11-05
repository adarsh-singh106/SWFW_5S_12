#!/usr/bin/env bash
# Master One-Shot GCE Deployment Orchestrator for Linux Fleet Manager
# Default mode is --dry-run. Live cloud mutation requires --execute.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=00-config.env
source "${SCRIPT_DIR}/00-config.env"

EXECUTE=false
CONFIRM_YES=false
TARGET_STEP=""
BUNDLE_PATH=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --execute)
      EXECUTE=true
      shift
      ;;
    --dry-run)
      EXECUTE=false
      shift
      ;;
    --yes|-y)
      CONFIRM_YES=true
      shift
      ;;
    --step)
      TARGET_STEP="$2"
      shift 2
      ;;
    --bundle)
      BUNDLE_PATH="$2"
      shift 2
      ;;
    -h|--help)
      echo "Usage: $0 [--dry-run | --execute] [--yes] [--step <1-7>] [--bundle <path>]"
      echo "  --dry-run   (Default) Validate and print complete deployment sequence without changes."
      echo "  --execute   Execute live end-to-end deployment in GCP."
      echo "  --yes       Skip confirmation prompt when executing."
      echo "  --step <N>  Run only specific step (1=start, 2=nodes, 3=controller, 4=app, 5=keys, 6=tunnel, 7=cleanup)."
      echo "  --bundle    Custom path to verified source bundle tarball."
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

echo "================================================================================"
echo "    SWFW_5S_12: Google Cloud Fleet Manager One-Shot Deployment Orchestrator"
echo "================================================================================"
echo "Target Project: ${GCP_PROJECT}"
echo "Target Zone:    ${GCP_ZONE}"
echo "Controller:     ${CONTROLLER_VM} (${CONTROLLER_IP})"
echo "Nodes:          ${NODE_A_VM} (${NODE_A_IP}), ${NODE_B_VM} (${NODE_B_IP}), ${NODE_C_VM} (${NODE_C_IP})"
echo "SSH Identity:   User '${NODE_SSH_USER}' via Cloud Shell key '${BOOTSTRAP_KEY_PATH}'"
echo "Mode:           $([ "${EXECUTE}" = "true" ] && echo "LIVE CLOUD EXECUTION" || echo "DRY-RUN (Simulated)")"
echo "================================================================================"

if [ "${EXECUTE}" = "true" ] && [ "${CONFIRM_YES}" != "true" ]; then
  echo ""
  echo "[WARNING] You have selected LIVE EXECUTION against Google Cloud."
  echo "Target project is: ${GCP_PROJECT}"
  echo "Target zone is:    ${GCP_ZONE}"
  read -r -p "Type 'DEPLOY' to confirm and start: " CONFIRMATION
  if [ "${CONFIRMATION}" != "DEPLOY" ]; then
    echo "[ABORTED] Confirmation did not match 'DEPLOY'. Exiting."
    exit 1
  fi
fi

run_step() {
  local step_num="$1"
  local step_script="$2"
  local step_desc="$3"
  shift 3 || true

  if [ -n "${TARGET_STEP}" ] && [ "${TARGET_STEP}" != "${step_num}" ]; then
    return 0
  fi

  echo ""
  echo ">>> [Step ${step_num}] ${step_desc} <<<"
  if [ "${EXECUTE}" = "true" ]; then
    bash "${SCRIPT_DIR}/${step_script}" --execute "$@"
  else
    bash "${SCRIPT_DIR}/${step_script}" --dry-run "$@"
  fi
}

# Step 1: Start VMs
run_step "1" "01-start-vms.sh" "Start all four GCE VMs and wait for RUNNING"

# Step 2: Provision Node Exporter on managed nodes
run_step "2" "02-setup-nodes.sh" "Provision Node Exporter across nodes A, B, and C"

# Step 3: Setup controller system dependencies, Python 3.12, Prometheus, Grafana
run_step "3" "03-setup-controller.sh" "Provision controller dependencies, Prometheus, Grafana"

# Step 4: Deploy application release, locked dependencies, systemd units
EXTRA_APP_ARGS=()
if [ -n "${BUNDLE_PATH}" ]; then
  EXTRA_APP_ARGS+=("--bundle" "${BUNDLE_PATH}")
fi
run_step "4" "04-deploy-app.sh" "Deploy application code, locked sync, systemd services" ${EXTRA_APP_ARGS[@]+"${EXTRA_APP_ARGS[@]}"}

# Step 5: Transfer bootstrap SSH private key and setup known_hosts
run_step "5" "05-transfer-keys.sh" "Transfer bootstrap credentials and configure known_hosts"

# Step 6: Inform about access tunnels
run_step "6" "06-start-tunnel.sh" "Operational access: IAP SSH port forwarding"

if [ "${TARGET_STEP}" = "7" ]; then
  run_step "7" "07-cleanup-vms.sh" "Teardown: Stop all VMs and report storage costs"
fi

echo ""
echo "================================================================================"
if [ "${EXECUTE}" = "true" ]; then
  echo "[COMPLETE] Deployment sequence finished successfully."
  echo "To launch local browser access:"
  echo "  bash ${SCRIPT_DIR}/06-start-tunnel.sh --execute"
  echo "Then run the automated acceptance test suite:"
  echo "  python scripts/gce_acceptance_test.py --host 127.0.0.1 --port 8000"
else
  echo "[COMPLETE] Dry-run validation finished. All scripts and paths verified."
  echo "To execute against live GCP instances, run:"
  echo "  bash ${SCRIPT_DIR}/deploy-all.sh --execute"
fi
echo "================================================================================"
