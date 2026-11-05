#!/usr/bin/env bash
# Step 06: Start local SSH port forwarding tunnel through IAP to controller loopback ports.
# Forwards local 8000 -> controller 127.0.0.1:8000 (Fleet Manager Dashboard)
# Forwards local 9090 -> controller 127.0.0.1:9090 (Prometheus API)
# Forwards local 3000 -> controller 127.0.0.1:3000 (Grafana Operational Dashboard)

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
      echo "  --dry-run  (Default) Print tunnel command and endpoints."
      echo "  --execute  Launch live background or foreground IAP SSH tunnel."
      exit 0
      ;;
  esac
done

echo "============================================================"
echo "GCE Operational Access: Secure IAP SSH Port Forwarding Tunnel"
echo "Target Controller: ${CONTROLLER_VM} (127.0.0.1)"
echo "Endpoints forwarded to local workstation:"
echo "  Fleet Manager UI:     http://127.0.0.1:8000/dashboard"
echo "  Fleet Metrics:        http://127.0.0.1:8000/metrics"
echo "  Prometheus API:       http://127.0.0.1:9090"
echo "  Grafana Dashboard:    http://127.0.0.1:3000"
echo "Security: Services bind strictly to 127.0.0.1; zero public or VPC ingress exposure."
echo "============================================================"

TUNNEL_CMD="gcloud compute ssh \"${CONTROLLER_VM}\" \\
  --project=\"${GCP_PROJECT}\" \\
  --zone=\"${GCP_ZONE}\" \\
  --tunnel-through-iap \\
  -- -N -o ExitOnForwardFailure=yes -L 127.0.0.1:8000:127.0.0.1:8000 -L 127.0.0.1:3000:127.0.0.1:3000 -L 127.0.0.1:9090:127.0.0.1:9090"

if [ "${EXECUTE}" != "true" ]; then
  echo "[DRY-RUN] Live execution skipped. To open tunnel, pass --execute."
  echo "[DRY-RUN] Command:"
  echo "  ${TUNNEL_CMD}"
  exit 0
fi

echo "[*] Starting secure IAP tunnel in foreground (Press Ctrl+C to stop)..."
eval "${TUNNEL_CMD}"
