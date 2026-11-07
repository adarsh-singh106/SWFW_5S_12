"""Fleet Health consumes only real shaped Prometheus series for known nodes."""

import time

import httpx
import pytest
from fastapi.testclient import TestClient

from fleet_manager.errors import InvalidNode
from fleet_manager.inventory.models import validate_new_node
from fleet_manager.main import create_app
from fleet_manager.metrics.health import PrometheusHealth


def _response(value: str = "1", *, empty: bool = False, stale: bool = False) -> httpx.Response:
    stamp = time.time() - (200 if stale else 1)
    rows = (
        []
        if empty
        else [
            {
                "metric": {"node_id": "1", "instance": "node-a:9100"},
                "value": [stamp, value],
                "values": [[stamp, value]],
            }
        ]
    )
    return httpx.Response(
        200, json={"status": "success", "data": {"resultType": "vector", "result": rows}}
    )


@pytest.mark.parametrize("mode", ["success", "down", "stale", "timeout"])
def test_health_target_states(client, mode: str) -> None:
    node_id = client.post(
        "/api/nodes", json={"name": "node-a", "address": "node-a", "ssh_port": 22}
    ).json()["id"]
    captured: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        query = request.url.params["query"]
        captured.append(query)
        assert 'job="node_exporter"' in query
        assert (
            query == f'up{{job="node_exporter",node_id="{node_id}"}}'
            or 'instance="node-a:9100"' in query
        )
        if mode == "timeout":
            raise httpx.ReadTimeout("test timeout")
        if request.url.path.endswith("query_range"):
            stamp = time.time() - 1
            return httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": {
                        "resultType": "matrix",
                        "result": [{"metric": {}, "values": [[stamp, "1"]]}],
                    },
                },
            )
        if query.startswith("up{"):
            return _response("0" if mode == "down" else "1", stale=mode == "stale")
        return _response("1073741824")

    client.app.state.prometheus_health = PrometheusHealth(transport=httpx.MockTransport(respond))
    response = client.get(f"/api/nodes/{node_id}/health")
    assert response.status_code == 200
    body = response.json()
    assert (
        body["status"]
        == {"success": "up", "down": "down", "stale": "stale", "timeout": "unavailable"}[mode]
    )
    if mode == "success":
        assert body["metrics"]["memory_total_bytes"] == 1073741824
        assert body["trends"]["cpu_percent"]
    else:
        assert all(value is None for value in body["metrics"].values()) or body["metrics"] == {}
    assert captured


def test_health_rejects_unknown_nodes_and_promql(client, unauthenticated_client) -> None:
    registered = client.post(
        "/api/nodes", json={"name": "node-a", "address": "192.168.1.10", "ssh_port": 22}
    ).json()["id"]
    assert client.get("/api/nodes/999999/health").status_code == 404
    assert client.get(f"/api/nodes/{registered}/health?query=up").status_code == 400
    assert unauthenticated_client.get(f"/api/nodes/{registered}/health").status_code == 401


@pytest.mark.parametrize(
    ("address", "normalized"),
    [
        ("192.168.1.10", "192.168.1.10"),
        ("2001:db8::1", "2001:db8::1"),
        ("node-a.example.com", "node-a.example.com"),
        ("NODE-A", "node-a"),
    ],
)
def test_registration_accepts_address_syntax_without_dns(monkeypatch, address, normalized) -> None:
    def forbidden_dns(*_args, **_kwargs):
        raise AssertionError("registration must not resolve DNS")

    monkeypatch.setattr("socket.getaddrinfo", forbidden_dns)
    assert validate_new_node("node", address, 22).address == normalized


@pytest.mark.parametrize(
    "address", ["999.999.999.999", "bad..name", "-host", "host_underscore", "[::1]", "2001:db8::zz"]
)
def test_registration_rejects_malformed_addresses(address) -> None:
    with pytest.raises(InvalidNode):
        validate_new_node("node", address, 22)


def test_health_denied_during_mandatory_password_change(tmp_path) -> None:
    with TestClient(
        create_app(database_path=tmp_path / "inventory.db", initial_password="CHANGEME")
    ) as client:
        login = client.post("/api/auth/login", json={"password": "CHANGEME"})
        assert login.status_code == 200
        assert client.get("/api/nodes/1/health").status_code == 401


def test_missing_target_or_metric_is_unavailable_not_zero(client) -> None:
    node_id = client.post(
        "/api/nodes", json={"name": "node-a", "address": "node-a", "ssh_port": 22}
    ).json()["id"]

    def missing_target(_request: httpx.Request) -> httpx.Response:
        return _response(empty=True)

    client.app.state.prometheus_health = PrometheusHealth(
        transport=httpx.MockTransport(missing_target)
    )
    missing = client.get(f"/api/nodes/{node_id}/health").json()
    assert missing == {"status": "unavailable", "observed_at": None, "metrics": {}, "trends": {}}

    def missing_metric(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("query_range"):
            return httpx.Response(
                200, json={"status": "success", "data": {"resultType": "matrix", "result": []}}
            )
        return (
            _response() if request.url.params["query"].startswith("up{") else _response(empty=True)
        )

    client.app.state.prometheus_health = PrometheusHealth(
        transport=httpx.MockTransport(missing_metric)
    )
    partial = client.get(f"/api/nodes/{node_id}/health").json()
    assert partial["status"] == "up"
    assert all(value is None for value in partial["metrics"].values())


def test_bad_prometheus_configuration_keeps_health_endpoint_available(client) -> None:
    node_id = client.post(
        "/api/nodes", json={"name": "node-a", "address": "node-a", "ssh_port": 22}
    ).json()["id"]
    client.app.state.prometheus_health = PrometheusHealth(base_url="file:///etc/passwd")
    assert client.get(f"/api/nodes/{node_id}/health").json()["status"] == "unavailable"


def test_existing_gcp_node_name_target_maps_hostname_inventory_to_private_exporter(client) -> None:
    node_id = client.post(
        "/api/nodes",
        json={"name": "fleet-node-a", "address": "fleet-node-a.internal", "ssh_port": 22},
    ).json()["id"]
    queries = []

    def respond(request: httpx.Request) -> httpx.Response:
        query = request.url.params["query"]
        queries.append(query)
        if query.startswith("up{"):
            stamp = time.time()
            return httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": {
                        "resultType": "vector",
                        "result": [
                            {
                                "metric": {
                                    "node_name": "fleet-node-a",
                                    "instance": "10.160.0.5:9100",
                                },
                                "value": [stamp, "1"],
                            }
                        ],
                    },
                },
            )
        if request.url.path.endswith("query_range"):
            return httpx.Response(
                200, json={"status": "success", "data": {"resultType": "matrix", "result": []}}
            )
        return _response("2")

    client.app.state.prometheus_health = PrometheusHealth(transport=httpx.MockTransport(respond))
    result = client.get(f"/api/nodes/{node_id}/health").json()
    assert result["status"] == "up"
    assert result["metrics"]["load_one"] == 2
    assert any('node_name="fleet-node-a"' in query for query in queries)
    assert all(
        'instance="10.160.0.5:9100"' in query for query in queries if not query.startswith("up{")
    )
