# Practice 04: HTTP API Layer (FastAPI Web Controller)

> Commit review by Codex, 2026-10-16: run from this practice directory with FastAPI, Pydantic v2, and Uvicorn installed. In-process ASGI checks passed for 201/400/409/422 and listing after registration; live HTTP was not checked. GET before any registration currently fails because the table has not been initialized.

**Series:** Fleet Manager Hands-on Practice\
**Topic:** Feature 1 — Node Inventory (HTTP API Layer)\
**Parent Lesson:** [⬅️ Document 07: The HTTP API Layer](../07-http-api-layer.md)\
**Associated Code:** [`app.py`](app.py)

---

## 1. Objective

Is practice exercise mein hum ek HTTP web server banayenge: **`app.py`** using **FastAPI**.\
Yeh server hamare service layer ko network ke upar expose karega:

1. **`POST /api/nodes`**: JSON payload accept karega, `register_node()` ko call karega, aur:
   * Success par `201 Created` return karega.
   * Input validation error par `400 Bad Request` return karega.
   * Duplicate node par `409 Conflict` return karega.
2. **`GET /api/nodes`**: Fleet ki registered nodes list return karega (`200 OK`).

---

## 2. The Lego Blocks / Syntax Cheatsheet

FastAPI ka syntax bohot clean aur readable hai. Yeh rahe tere building blocks:

### Tool 1: Imports & App Initialization
```python
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel
from node_service import register_node
from db_storage import list_nodes

app = FastAPI(title="Distributed Linux Fleet Manager")
```

### Tool 2: Request Model (Pydantic / Dict Contract)
```python
class NodeRegistrationRequest(BaseModel):
    name: str
    address: str
    port: int = 22  # Default SSH port
```

### Tool 3: POST Route with Error Mapping
```python
@app.post("/api/nodes", status_code=status.HTTP_201_CREATED)
def add_new_node(payload: NodeRegistrationRequest):
    try:
        # Convert Pydantic model to dictionary for our service layer
        node_data = payload.model_dump()
        result = register_node(node_data)
        return result
    except ValueError as e:
        error_msg = str(e)
        if "already exists" in error_msg:
            # 409 Conflict for duplicate IP:Port
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error_msg)
        # 400 Bad Request for validation errors (e.g. bad port)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)
```

### Tool 4: GET Route (Listing Fleet Nodes)
```python
@app.get("/api/nodes", status_code=status.HTTP_200_OK)
def get_fleet_nodes():
    nodes = list_nodes()
    return {"nodes": nodes}
```

---

## 3. How to Run & Test

Server start karne ka command:
```powershell
python -m uvicorn app:app --reload --port 8000
```

Browser mein interactive Swagger documentation test karne ke liye:
👉 `http://127.0.0.1:8000/docs`
