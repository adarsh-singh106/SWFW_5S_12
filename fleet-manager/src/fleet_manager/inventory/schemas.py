"""HTTP representations for inventory records."""

from pydantic import BaseModel, ConfigDict

from fleet_manager.inventory.models import Node, ObservationState


class NodeRegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str
    address: str
    ssh_port: int = 22


class NodeResponse(BaseModel):
    id: int
    name: str
    address: str
    ssh_port: int
    observation_state: ObservationState

    @classmethod
    def from_node(cls, node: Node) -> "NodeResponse":
        return cls(
            id=node.id,
            name=node.name,
            address=node.address,
            ssh_port=node.ssh_port,
            observation_state=node.observation_state,
        )


class NodeListResponse(BaseModel):
    nodes: list[NodeResponse]


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
