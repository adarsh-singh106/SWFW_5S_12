from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel
from node_service import register_node
from db_storage import list_nodes

app = FastAPI(title="Distributed Linux Fleet Manager")


# kinda of defining schema
class NodeRegistrationRequest(BaseModel):
    name: str
    address: str
    port: int = 22  # Default SSH port

    # we can also apply validaton in pydantic ! it will reject incorrect
    # data coming from frontend part and wont touch our API's

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
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Node is already registered")
        # 400 Bad Request for validation errors (e.g. bad port)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid port Number")


@app.get("/api/nodes", status_code=status.HTTP_200_OK)
def get_fleet_nodes():
    nodes = list_nodes()
    return {"nodes": nodes}
