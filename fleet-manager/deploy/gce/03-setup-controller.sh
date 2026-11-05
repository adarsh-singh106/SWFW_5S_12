#!/usr/bin/env bash
# Step 03: Provision controller host dependencies, standalone Python 3.12, Prometheus, and Grafana.
# Default mode is --dry-run. Live cloud mutation requires --execute.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=00-config.env
source "${SCRIPT_DIR}/00-config.env"

EXECUTE=false
LOCAL_RUN=false
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
    --local)
      LOCAL_RUN=true
      shift
      ;;
    -h|--help)
      echo "Usage: $0 [--dry-run | --execute] [--local]"
      echo "  --dry-run  (Default) Print commands without executing live changes."
      echo "  --execute  Execute live controller setup."
      echo "  --local    Run directly on the controller machine (used when executing on the host itself)."
      exit 0
      ;;
  esac
done

echo "============================================================"
echo "GCE Deployment - Step 03: Provision Controller System"
echo "Controller: ${CONTROLLER_VM} (${CONTROLLER_IP})"
echo "============================================================"

CONTROLLER_SCRIPT=$(cat << 'EOF'
set -euo pipefail

echo "[1/6] Installing controller base system packages..."
sudo apt-get update && sudo apt-get install -y \
  apt-transport-https \
  software-properties-common \
  wget \
  gpg \
  curl \
  git \
  sqlite3 \
  openssh-client \
  prometheus \
  prometheus-node-exporter

echo "[2/6] Installing official Grafana package repository..."
sudo mkdir -p /etc/apt/keyrings
if [ ! -f /etc/apt/keyrings/grafana.gpg ]; then
  curl -fsSL https://apt.grafana.com/gpg.key | sudo gpg --dearmor -o /etc/apt/keyrings/grafana.gpg
fi
echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main" | sudo tee /etc/apt/sources.list.d/grafana.list
sudo apt-get update && sudo apt-get install -y grafana

echo "[3/6] Installing Astral uv standalone toolchain..."
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  sudo install -m 755 "${HOME}/.local/bin/uv" /usr/local/bin/uv
fi

echo "[4/6] Creating service user and directory tree..."
if ! id -u fleet-manager >/dev/null 2>&1; then
  sudo useradd -r -s /usr/sbin/nologin -d /var/lib/fleet-manager -m fleet-manager
fi

sudo mkdir -p /opt/fleet-manager
sudo mkdir -p /etc/fleet-manager
sudo mkdir -p /var/lib/fleet-manager
sudo mkdir -p /var/backups/fleet-manager

sudo chown -R fleet-manager:fleet-manager /var/lib/fleet-manager /var/backups/fleet-manager /etc/fleet-manager
sudo chmod 700 /var/lib/fleet-manager /var/backups/fleet-manager /etc/fleet-manager

echo "[5/6] Installing hermetic CPython 3.12 for Ubuntu 26.04 compatibility..."
sudo env UV_PYTHON_INSTALL_DIR=/opt/fleet-manager/python /usr/local/bin/uv python install 3.12
PYTHON_BIN="$(sudo env UV_PYTHON_INSTALL_DIR=/opt/fleet-manager/python /usr/local/bin/uv python find 3.12)"
echo "Hermetic Python binary located at: ${PYTHON_BIN}"

echo "[6/6] Configuring Prometheus and Grafana targets..."
# Deploy targets.json with actual three-node GCE internal IPs
cat << 'TARGETS_EOF' | sudo tee /etc/prometheus/targets.json
[
  {
    "targets": ["10.160.0.5:9100"],
    "labels": {
      "node_name": "fleet-node-a",
      "job": "node_exporter",
      "fleet": "gcp-production"
    }
  },
  {
    "targets": ["10.160.0.3:9100"],
    "labels": {
      "node_name": "fleet-node-b",
      "job": "node_exporter",
      "fleet": "gcp-production"
    }
  },
  {
    "targets": ["10.160.0.4:9100"],
    "labels": {
      "node_name": "fleet-node-c",
      "job": "node_exporter",
      "fleet": "gcp-production"
    }
  }
]
TARGETS_EOF

sudo chown -R prometheus:prometheus /etc/prometheus
sudo chmod 644 /etc/prometheus/targets.json
sudo systemctl enable --now prometheus
sudo systemctl enable --now grafana-server
sudo systemctl restart prometheus grafana-server

echo "[SUCCESS] Controller prerequisites, Prometheus, and Grafana provisioned successfully."
EOF
)

if [ "${LOCAL_RUN}" = "true" ]; then
  if [ "${EXECUTE}" != "true" ]; then
    echo "[DRY-RUN] Local execution skipped. Pass --execute --local to run on this host."
    exit 0
  fi
  bash -c "${CONTROLLER_SCRIPT}"
  exit 0
fi

if [ "${EXECUTE}" != "true" ]; then
  echo "[DRY-RUN] Live execution skipped. To execute on ${CONTROLLER_VM} via IAP, pass --execute."
  echo "[DRY-RUN] Would execute remote script on ${CONTROLLER_VM}."
  exit 0
fi

echo "[*] Live execution confirmed. Dispatching provisioning to ${CONTROLLER_VM} via IAP SSH..."
gcloud compute ssh "${CONTROLLER_VM}" \
  --project="${GCP_PROJECT}" \
  --zone="${GCP_ZONE}" \
  --tunnel-through-iap \
  --command="${CONTROLLER_SCRIPT}"

echo "[SUCCESS] Controller provisioning complete."
