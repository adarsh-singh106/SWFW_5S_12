"""Inventory use cases independent of HTTP."""

from fleet_manager.inventory.models import Node, validate_new_node
from fleet_manager.inventory.repository import SQLiteNodeRepository


class NodeService:
    def __init__(self, repository: SQLiteNodeRepository) -> None:
        self.repository = repository

    def register(self, name: str, address: str, ssh_port: int) -> Node:
        new_node = validate_new_node(name, address, ssh_port)
        return self.repository.add_node(new_node)

    def list_nodes(self) -> list[Node]:
        return self.repository.list_nodes()
