import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from node_service import register_node, probe_node
from db_storage import list_nodes
from command_dispatcher import execute_action, list_audit_logs, COMMAND_CATALOG

STATIC_FILE_PATH = os.path.join(os.path.dirname(__file__), "static", "index.html")


async def background_probe_worker():
    """
    Background worker that runs every 15 seconds to periodically probe all
    registered nodes without blocking the FastAPI async event loop.
    """
    while True:
        try:
            nodes = list_nodes()
            for node in nodes:
                try:
                    # Offload synchronous socket probe to a thread pool executor
                    await asyncio.to_thread(probe_node, node["id"])
                except Exception:
                    pass
        except Exception:
            pass
        await asyncio.sleep(15)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Launch background probe worker
    worker_task = asyncio.create_task(background_probe_worker())
    yield
    # Shutdown: Cancel worker task gracefully
    worker_task.cancel()


app = FastAPI(title="Distributed Linux Fleet Manager", lifespan=lifespan)


class NodeRegistrationRequest(BaseModel):
    name: str
    address: str
    port: int = 22  # Default SSH port


class ActionExecutionRequest(BaseModel):
    action: str
    params: dict | None = None


@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    """Serve the single-page HTML monitor dashboard."""
    if os.path.exists(STATIC_FILE_PATH):
        with open(STATIC_FILE_PATH, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>Dashboard index.html not found</h1>", status_code=404)


@app.post("/api/nodes", status_code=status.HTTP_201_CREATED)
def add_new_node(payload: NodeRegistrationRequest):
    try:
        node_data = payload.model_dump()
        result = register_node(node_data)
        return result
    except ValueError as e:
        error_msg = str(e)
        if "already exists" in error_msg:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Node is already registered")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)


@app.get("/api/nodes", status_code=status.HTTP_200_OK)
def get_fleet_nodes():
    nodes = list_nodes()
    return {"nodes": nodes}


@app.post("/api/nodes/{node_id}/probe", status_code=status.HTTP_200_OK)
def probe_existing_node(node_id: int):
    try:
        updated_node = probe_node(node_id)
        return updated_node
    except ValueError as e:
        error_msg = str(e)
        if "does not exist" in error_msg:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=error_msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)


@app.get("/api/actions", status_code=status.HTTP_200_OK)
def get_action_catalog():
    """Return the guarded action catalog for frontend selection."""
    return {"catalog": COMMAND_CATALOG}


@app.post("/api/nodes/{node_id}/execute", status_code=status.HTTP_200_OK)
def run_node_action(node_id: int, payload: ActionExecutionRequest):
    """Execute a guarded action against a registered node with audit logging."""
    try:
        result = execute_action(
            node_id=node_id,
            action_name=payload.action,
            params=payload.params
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.get("/api/nodes/{node_id}/audit-logs", status_code=status.HTTP_200_OK)
def get_node_audit_logs(node_id: int):
    """Retrieve audit trail for a specific node."""
    return {"audit_logs": list_audit_logs(node_id=node_id)}


@app.get("/api/audit-logs", status_code=status.HTTP_200_OK)
def get_all_audit_logs():
    """Retrieve global fleet audit logs."""
    return {"audit_logs": list_audit_logs()}

