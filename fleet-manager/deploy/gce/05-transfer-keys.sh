#!/usr/bin/env bash
# Step 05: Transfer GCE bootstrap SSH private key securely and initialize writable known_hosts.
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
      echo "  --execute  Execute live key transfer and permission configuration."
      exit 0
      ;;
  esac
done

echo "============================================================"
echo "GCE Deployment - Step 05: Install Managed-Node SSH Credentials"
echo "Source Key:      ${BOOTSTRAP_KEY_PATH}"
echo "Destination:     ${CONTROLLER_VM}:${INSTALLED_PRIVATE_KEY} (0600, fleet-manager:fleet-manager)"
echo "Host Key Store:  ${CONTROLLER_VM}:${INSTALLED_KNOWN_HOSTS} (0600, fleet-manager:fleet-manager)"
echo "============================================================"

if [ "${EXECUTE}" != "true" ]; then
  echo "[DRY-RUN] Live execution skipped. To execute, pass --execute."
  echo "[DRY-RUN] Would copy ${BOOTSTRAP_KEY_PATH} via IAP SCP:"
  echo "  gcloud compute scp \"${BOOTSTRAP_KEY_PATH}\" \"${CONTROLLER_VM}:/tmp/fleet-bootstrap\" \\"
  echo "    --project=\"${GCP_PROJECT}\" \\"
  echo "    --zone=\"${GCP_ZONE}\" \\"
  echo "    --tunnel-through-iap"
  echo "[DRY-RUN] Would harden permissions on ${CONTROLLER_VM}:"
  echo "  sudo install -m 600 -o fleet-manager -g fleet-manager /tmp/fleet-bootstrap /etc/fleet-manager/id_ed25519"
  echo "  rm -f /tmp/fleet-bootstrap"
  echo "  sudo ssh-keygen -y -f /etc/fleet-manager/id_ed25519 | sudo tee /etc/fleet-manager/id_ed25519.pub"
  echo "  sudo chown fleet-manager:fleet-manager /etc/fleet-manager/id_ed25519.pub"
  echo "  sudo chmod 644 /etc/fleet-manager/id_ed25519.pub"
  echo "  sudo -u fleet-manager touch /var/lib/fleet-manager/known_hosts"
  echo "  sudo chmod 600 /var/lib/fleet-manager/known_hosts"
  exit 0
fi

if [ ! -f "${BOOTSTRAP_KEY_PATH}" ]; then
  echo "[ERROR] Local bootstrap key not found at ${BOOTSTRAP_KEY_PATH}" >&2
  exit 1
fi

echo "[*] Transferring bootstrap key to ${CONTROLLER_VM} via IAP SCP..."
gcloud compute scp "${BOOTSTRAP_KEY_PATH}" "${CONTROLLER_VM}:/tmp/fleet-bootstrap" \
  --project="${GCP_PROJECT}" \
  --zone="${GCP_ZONE}" \
  --tunnel-through-iap

echo "[*] Setting secure ownership and permissions on controller..."
gcloud compute ssh "${CONTROLLER_VM}" \
  --project="${GCP_PROJECT}" \
  --zone="${GCP_ZONE}" \
  --tunnel-through-iap \
  --command="sudo install -m 600 -o fleet-manager -g fleet-manager /tmp/fleet-bootstrap /etc/fleet-manager/id_ed25519 && \
             rm -f /tmp/fleet-bootstrap && \
             sudo ssh-keygen -y -f /etc/fleet-manager/id_ed25519 | sudo tee /etc/fleet-manager/id_ed25519.pub >/dev/null && \
             sudo chown fleet-manager:fleet-manager /etc/fleet-manager/id_ed25519.pub && \
             sudo chmod 644 /etc/fleet-manager/id_ed25519.pub && \
             sudo -u fleet-manager touch /var/lib/fleet-manager/known_hosts && \
             sudo chmod 600 /var/lib/fleet-manager/known_hosts"

echo "[SUCCESS] SSH private key and writable known_hosts installed securely."
