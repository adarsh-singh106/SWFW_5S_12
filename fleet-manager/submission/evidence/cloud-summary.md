# GCP read-only safety assessment — final closeout

Prepared 9 November 2026 using the existing gcloud session. Project and active principal were verified; principal email and raw SSH metadata remain only in local evidence, not this sanitized submission record. Project: project-3682976b-7d4a-465a-933; zone: asia-south1-a.

## Initial and final observations

Initial read window: 08:25:39–08:25:51 UTC. Final closeout: 08:39:25–08:39:35 UTC, 9 November 2026. All 19 closeout read-only requests succeeded. These are separate reads, not continuous or atomic monitoring.

| VM | Initial / final state | Initial / final internal IP | External IP / accessConfigs | Disk unchanged |
| --- | --- | --- | --- | --- |
| fleet-controller | RUNNING / RUNNING | 10.160.0.2 / 10.160.0.2 | None / absent in both | Same ID, attachment, 20 GiB pd-balanced, READY |
| fleet-node-a | RUNNING / RUNNING | 10.160.0.5 / 10.160.0.5 | None / absent in both | Same ID, attachment, 10 GiB pd-standard, READY |
| fleet-node-b | RUNNING / RUNNING | 10.160.0.3 / 10.160.0.3 | None / absent in both | Same ID, attachment, 10 GiB pd-standard, READY |
| fleet-node-c | RUNNING / RUNNING | 10.160.0.4 / 10.160.0.4 | None / absent in both | Same ID, attachment, 10 GiB pd-standard, READY |

Full allowlisted per-VM identity/NIC/accessConfig/disk projections and comparisons are included in cloud-sanitized.json. No reserved address or Cloud Router was returned in the inspected project; that is not proof of no guest/proxy egress. NIC external NAT accessConfig and Cloud NAT are different resources. No absent accessConfig was invented or restored.

## IAP and SSH safety gate: BLOCKED on all four

Effective NIC firewall reads permit 35.235.240.0/20 TCP22 for actual controller/node tag scope, with no returned higher-priority deny. Controller matching rule priority 65534; node matching rule priority 1000. Internal VPC SSH is also allowed, so observed rules are not proof of exclusively IAP ingress. No packet-path test was performed.

Project policy grants were observed, but full inherited deny/access-context/per-resource effective IAP authorization was not established. Installed stable CLI lacks the requested IAP policy read; beta help attempted component bootstrap and failed non-interactively. No installation workaround followed. This is a tooling/verification gap, not proof of denied permission.

Existing public identity matches controller OS Login and node-a instance authorization, not node-b/c instance keys. Private key file existence/ACL were inspected without reading contents; usable private/public pairing and guest authorization were not proved. Existing named known_hosts entries lack independently established current host-key provenance. This blocks strict identity verification. No key scan, key generation, upload, SSH, tunnel or port forward was attempted.

## Cleanup, normalization and evidence limits

No VM power/NAT/disk/firewall/IAM/metadata/SSH-key/VPC/route/DNS mutation occurred; no public IP was allocated by this run. Initially absent configurations stayed absent and all VMs stayed RUNNING. VM RUNNING and disk READY are control-plane states, not application/guest health.

Initial raw node-metadata comparisons differed because the collector initially could not parse username-prefixed SSH records; corrected parsing produced fingerprints. Metadata version fingerprints and non-SSH values stayed equal, and corrected-final versus closeout metadata matched. Original raw SSH key-content equality cannot be reconstructed from the first sanitized representation. Raw firewall ordering differences normalize to equal full rule content. The report does not falsely claim all initial raw metadata bytes were proved equal.

Deployed commit/build, /api/auth routes, native health, controller API readiness, Prometheus targets and actual scrape times/durations/errors, exporter endpoints, real CPU/memory/uptime/filesystem/network samples, internal DNS and Grafana service/panels are NOT freshly verified. Historical November 8 results remain historical, not current proof. No failure/recovery was manufactured. Next action requires independently authenticated host-key attestations and complete effective IAP/authorized identity proof before connectivity.
