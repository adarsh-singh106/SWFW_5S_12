# ADR 0007: Three-Endpoint Service Integration Topology and Failure Domain Boundaries

## Status
Accepted

## Context
Milestone SWFW_5S_12 requires demonstrating the Distributed Linux Fleet Manager managing three concurrent Linux targets. Safe local virtualization inspection confirmed that while the Windows 11 host runs WSL2 (Debian 12), independent hardware-virtualized VMs with separate OS/kernel failure domains (e.g. via VirtualBox or Hyper-V) are not provisioned. Falsely reporting multiple WSL distributions or namespaces as separate machines is strictly prohibited.

## Decision
1. **Three Isolated Service Endpoints**: We deploy three disposable target endpoints on loopback ports:
   - `endpoint-alpha`: SSH port `2201`, Node Exporter port `9101`, Node ID 1.
   - `endpoint-beta`: SSH port `2202`, Node Exporter port `9102`, Node ID 2.
   - `endpoint-gamma`: SSH port `2203`, Node Exporter port `9103`, Node ID 3.
2. **Explicit Failure Domain Labeling**:
   - **Shared Failure Domain**: The endpoints share the single WSL2 Linux kernel (`6.18.33.2-microsoft-standard-WSL2`), root filesystem, and underlying hardware metrics (CPU, RAM, root disk). A kernel panic or host reboot affects all three endpoints.
   - **Isolated Service Boundaries**: Each endpoint operates an independent OpenSSH daemon (`/usr/sbin/sshd`) and dedicated Node Exporter process with distinct PID lifecycles, dedicated TCP ports, and unique cryptographic host keys pinned in `known_hosts`.
3. **Verified Failure & Recovery Dynamics**:
   - **SSH Failure on Beta**: Killing `sshd` on port 2202 triggers `CONNECTION_REFUSED` and updates derived status to `UNREACHABLE` in 1.108s. Healthy peers `alpha` and `gamma` remain unaffected (`CONNECTED`), and the Node Exporter on port 9102 remains `up=1`. Restoring `sshd` achieves recovery to `REACHABLE` in 1.151s.
   - **Metrics Exporter Failure on Gamma**: Terminating Node Exporter on port 9103 triggers Prometheus `up=0` in 5.048s without impacting SSH connectivity (`CONNECTED`) or peer exporters (ports 9101, 9102 remain `up=1`). Restarting the exporter achieves recovery to `up=1` in 4.038s.
4. **Disposable Resources & Cleanup**:
   - Pinned keys, PID files, and custom configurations are generated in `/tmp/fleet_three_endpoints`.
   - Automated cleanup traps terminate all test daemons and restore original Prometheus configuration (`/etc/prometheus/targets.json`).

## Consequences
- Demonstrates real service-level multi-node orchestration, strict host key checking, independent failure isolation, Prometheus metric scraping, and remote operations across multiple concurrent endpoints.
- Unverified: Independent kernel/hardware failure domain resilience remains unproven until tested across distinct virtual or physical machines.
