#!/usr/bin/env bash
# Step 04: Deploy verified application source bundle, locked dependencies, configuration, and systemd services.
# Default mode is --dry-run. Live cloud mutation requires --execute.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=00-config.env
source "${SCRIPT_DIR}/00-config.env"

EXECUTE=false
LOCAL_RUN=false
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
    --local)
      LOCAL_RUN=true
      shift
      ;;
    --bundle)
      BUNDLE_PATH="$2"
      shift 2
      ;;
    -h|--help)
      echo "Usage: $0 [--dry-run | --execute] [--local] [--bundle <path/to/bundle.tar.gz>]"
      echo "  --dry-run  (Default) Print commands without executing live changes."
      echo "  --execute  Execute live application deployment."
      echo "  --local    Run directly on controller host."
      echo "  --bundle   Path to pre-packaged verified source bundle tarball."
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Resolve or generate source bundle
if [ -z "${BUNDLE_PATH}" ]; then
  DEFAULT_BUNDLE="${PROJECT_ROOT}/dist/fleet-manager-source-bundle.tar.gz"
  if [ -f "${DEFAULT_BUNDLE}" ]; then
    BUNDLE_PATH="${DEFAULT_BUNDLE}"
  elif [ -f "/tmp/fleet-manager-source-bundle.tar.gz" ]; then
    BUNDLE_PATH="/tmp/fleet-manager-source-bundle.tar.gz"
  else
    BUNDLE_PATH="${DEFAULT_BUNDLE}"
  fi
fi

echo "============================================================"
echo "GCE Deployment - Step 04: Deploy Fleet Manager Application"
echo "Target:        ${CONTROLLER_VM}"
echo "Source Bundle: ${BUNDLE_PATH}"
echo "============================================================"

APP_DEPLOY_SCRIPT=$(cat << 'EOF'
set -euo pipefail

cd /opt/fleet-manager

echo "[1/5] Synchronizing locked production virtual environment..."
PYTHON_BIN="$(sudo env UV_PYTHON_INSTALL_DIR=/opt/fleet-manager/python /usr/local/bin/uv python find 3.12)"
sudo env UV_LINK_MODE=copy /usr/local/bin/uv sync --locked --no-dev --python "$PYTHON_BIN"
sudo chmod -R a+rX /opt/fleet-manager/python /opt/fleet-manager/.venv

echo "[2/5] Configuring environment template and operator bearer token..."
if [ ! -f /etc/fleet-manager/fleet-manager.env ]; then
  sudo cp /opt/fleet-manager/deploy/fleet-manager.env.example /etc/fleet-manager/fleet-manager.env
  sudo chmod 600 /etc/fleet-manager/fleet-manager.env
  sudo chown fleet-manager:fleet-manager /etc/fleet-manager/fleet-manager.env

  SECRET_TOKEN=$(/opt/fleet-manager/.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(32))")
  sudo sed -i "s|REPLACE_WITH_GENERATED_32_TO_128_CHAR_SECRET_TOKEN|${SECRET_TOKEN}|g" /etc/fleet-manager/fleet-manager.env
  echo "  [OK] Generated unique operator secret in /etc/fleet-manager/fleet-manager.env"
else
  echo "  [INFO] Preserving existing /etc/fleet-manager/fleet-manager.env"
fi

echo "[3/5] Deploying Grafana dashboards and provisioning..."
sudo mkdir -p /etc/grafana/provisioning/datasources /etc/grafana/provisioning/dashboards /etc/grafana/dashboards
sudo cp /opt/fleet-manager/monitoring/grafana/provisioning/datasources/prometheus.yaml /etc/grafana/provisioning/datasources/
sudo cp /opt/fleet-manager/monitoring/grafana/provisioning/dashboards/dashboards.yaml /etc/grafana/provisioning/dashboards/
sudo cp /opt/fleet-manager/monitoring/grafana/dashboards/fleet-monitoring.json /etc/grafana/dashboards/
sudo chown -R grafana:grafana /etc/grafana/provisioning /etc/grafana/dashboards

echo "[4/5] Deploying Prometheus scrape configuration..."
sudo cp /opt/fleet-manager/monitoring/prometheus/prometheus.yml /etc/prometheus/prometheus.yml
sudo chown -R prometheus:prometheus /etc/prometheus

echo "[5/5] Installing systemd services..."
sudo cp /opt/fleet-manager/deploy/fleet-manager.service /etc/systemd/system/
sudo cp /opt/fleet-manager/deploy/fleet-manager-backup.service /etc/systemd/system/
sudo cp /opt/fleet-manager/deploy/fleet-manager-backup.timer /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable --now fleet-manager.service
sudo systemctl enable --now fleet-manager-backup.timer
sudo systemctl restart prometheus grafana-server

echo "[SUCCESS] Application and monitoring systemd services running."
EOF
)

if [ "${LOCAL_RUN}" = "true" ]; then
  if [ "${EXECUTE}" != "true" ]; then
    echo "[DRY-RUN] Local execution skipped. Pass --execute --local to run on this host."
    exit 0
  fi
  bash -c "${APP_DEPLOY_SCRIPT}"
  exit 0
fi

if [ "${EXECUTE}" != "true" ]; then
  echo "[DRY-RUN] Live execution skipped. To execute on ${CONTROLLER_VM} via IAP, pass --execute."
  echo "[DRY-RUN] Verified bundle path: ${BUNDLE_PATH}"
  echo "[DRY-RUN] Would verify bundle checksum via: sha256sum -c ${BUNDLE_PATH}.sha256"
  echo "[DRY-RUN] Would SCP bundle to ${CONTROLLER_VM}:/tmp/fleet-manager-source-bundle.tar.gz"
  echo "[DRY-RUN] Would verify SHA-256 and untar to /opt/fleet-manager on ${CONTROLLER_VM}"
  echo "[DRY-RUN] Would run application setup, locked uv sync, and start systemd services."
  exit 0
fi

# Ensure bundle exists or create it
if [ ! -f "${BUNDLE_PATH}" ]; then
  echo "[*] Bundle not found at ${BUNDLE_PATH}. Generating from current working tree..."
  python3 "${PROJECT_ROOT}/scripts/package_source_bundle.py" --output-dir "${PROJECT_ROOT}/dist"
  BUNDLE_PATH="${PROJECT_ROOT}/dist/fleet-manager-source-bundle.tar.gz"
fi

SHA256_FILE="${BUNDLE_PATH}.sha256"
if [ ! -f "${SHA256_FILE}" ]; then
  sha256sum "${BUNDLE_PATH}" > "${SHA256_FILE}"
fi

echo "[*] Pre-flight: Verifying bundle integrity and checksum..."
cd "$(dirname "${BUNDLE_PATH}")" && sha256sum -c "$(basename "${SHA256_FILE}")"

echo "[*] Live execution confirmed. Transferring verified source bundle to ${CONTROLLER_VM} via IAP SCP..."
gcloud compute scp "${BUNDLE_PATH}" "${CONTROLLER_VM}:/tmp/fleet-manager-source-bundle.tar.gz" \
  --project="${GCP_PROJECT}" \
  --zone="${GCP_ZONE}" \
  --tunnel-through-iap

gcloud compute scp "${SHA256_FILE}" "${CONTROLLER_VM}:/tmp/fleet-manager-source-bundle.tar.gz.sha256" \
  --project="${GCP_PROJECT}" \
  --zone="${GCP_ZONE}" \
  --tunnel-through-iap

echo "[*] Extracting verified bundle on ${CONTROLLER_VM}..."
EXTRACT_CMD="sudo mkdir -p /opt/fleet-manager && \
  cd /tmp && sha256sum -c fleet-manager-source-bundle.tar.gz.sha256 && \
  sudo tar -xzf /tmp/fleet-manager-source-bundle.tar.gz -C /opt/fleet-manager/ && \
  rm -f /tmp/fleet-manager-source-bundle.tar.gz /tmp/fleet-manager-source-bundle.tar.gz.sha256 && \
  sudo chown -R root:root /opt/fleet-manager && \
  sudo chmod -R go-w /opt/fleet-manager && \
  test -f /opt/fleet-manager/src/fleet_manager/main.py && \
  test -f /opt/fleet-manager/uv.lock"

gcloud compute ssh "${CONTROLLER_VM}" \
  --project="${GCP_PROJECT}" \
  --zone="${GCP_ZONE}" \
  --tunnel-through-iap \
  --command="${EXTRACT_CMD}"

echo "[*] Running application deployment and systemd configuration on ${CONTROLLER_VM}..."
gcloud compute ssh "${CONTROLLER_VM}" \
  --project="${GCP_PROJECT}" \
  --zone="${GCP_ZONE}" \
  --tunnel-through-iap \
  --command="${APP_DEPLOY_SCRIPT}"

echo "[SUCCESS] Fleet Manager release deployed and services started."
