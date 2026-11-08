"""Fleet Health consumes only real shaped Prometheus series for known nodes."""

import time

import httpx
import pytest
from fastapi.testclient import TestClient

from fleet_manager.errors import InvalidNode
from fleet_manager.inventory.models import validate_new_node
from fleet_manager.main import create_app
from fleet_manager.metrics.health import PrometheusHealth


@pytest.mark.parametrize("bad", ["-1", "101", "NaN", "Infinity"])
def test_history_rejects_invalid_percent_and_uses_source_timestamps(client, bad):
    node_id = client.post(
        "/api/nodes", json={"name": "node-a", "address": "node-a", "ssh_port": 22}
    ).json()["id"]
    now = time.time()

    def respond(request):
        query = request.url.params["query"]
        end = float(request.url.params.get("end", request.url.params.get("time", now)))
        source = "timestamp(" in query
        if request.url.path.endswith("query_range"):
            points = [
                [end - 300, str(end - 310) if source else "25"],
                [end - 150, str(end - 160) if source else bad],
                [end, str(end + 10) if source else "30"],
            ]
            return httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": {"resultType": "matrix", "result": [{"metric": {}, "values": points}]},
                },
            )
        if query.startswith("up{"):
            return _response()
        return _response(str(now - 20) if source else "25")

    client.app.state.prometheus_health = PrometheusHealth(transport=httpx.MockTransport(respond))
    body = client.get(f"/api/nodes/{node_id}/health").json()
    assert body["observed_at"] == now - 20
    points = body["trends"]["cpu_percent"]
    assert points[0] == [body["window"]["end"] - 310, 25]
    assert all(p[0] <= body["window"]["end"] for p in points)
    assert all(p[1] is None or 0 <= p[1] <= 100 for p in points)
    if bad in ("-1", "101", "NaN", "Infinity"):
        assert points[1][1] is None


@pytest.mark.parametrize("age,status", [(200, "stale"), (-200, "unavailable")])
def test_target_freshness_uses_source_not_current_evaluation(client, age, status):
    node_id = client.post(
        "/api/nodes", json={"name": "node-a", "address": "node-a", "ssh_port": 22}
    ).json()["id"]
    source_time = time.time() - age

    def respond(request):
        return (
            _response(str(source_time))
            if "timestamp(" in request.url.params["query"]
            else _response()
        )

    client.app.state.prometheus_health = PrometheusHealth(transport=httpx.MockTransport(respond))
    body = client.get(f"/api/nodes/{node_id}/health").json()
    assert body["status"] == status
    assert body["metrics"] == {}
    assert body["observed_at"] == (source_time if age > 0 else None)


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
        if "timestamp(" in query:
            if request.url.path.endswith("query_range"):
                evaluation = float(request.url.params["end"])
                return httpx.Response(
                    200,
                    json={
                        "status": "success",
                        "data": {
                            "resultType": "matrix",
                            "result": [
                                {"metric": {}, "values": [[evaluation, str(evaluation - 2)]]}
                            ],
                        },
                    },
                )
            return _response(str(time.time() - (200 if mode == "stale" else 2)))
        captured.append(query)
        assert 'job="node_exporter"' in query
        assert (
            query == f'up{{job="node_exporter",node_id="{node_id}"}}'
            or 'instance="node-a:9100"' in query
        )
        if mode == "timeout":
            raise httpx.ReadTimeout("test timeout")
        if request.url.path.endswith("query_range"):
            stamp = float(request.url.params["end"])
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
        if "timestamp(up{" in request.url.params["query"]:
            return _response(str(time.time() - 2))
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
        if "timestamp(" in query:
            return _response(str(time.time() - 2))
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
