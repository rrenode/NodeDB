# database.py
from enum import Enum
from typing import Any, Dict, Optional
from uuid import uuid4, UUID
from pathlib import Path
import jsonpickle
import difflib

from .utils import OldVariableNamesMeta, generate_name_alias

class BaseModel(metaclass=OldVariableNamesMeta):
    def __getstate__(self) -> Dict[str, Any]:
        """
        When jsonpickle pickles us, export all public names from the class and its ancestors.
        """
        state: Dict[str, Any] = {}
        annotations: Dict[str, Any] = {}
        
        # Walk MRO to include inherited fields
        for cls in self.__class__.__mro__:
            annotations.update(getattr(cls, "__annotations__", {}))
        
        for public in annotations:
            state[public] = getattr(self, public, None)
        
        return state

    def __setstate__(self, state: Dict[str, Any]):
        """
        When jsonpickle rehydrates us:
        1. Rename any old → new keys
        2. Assign via setattr so the AutoPropertiesMeta
           setters populate the private backing fields.
        """
        old_map = getattr(self.__class__, "__old_mappings__", {})
        for old, new in old_map.items():
            if old in state:
                state[new] = state.pop(old)

        for public, val in state.items():
            setattr(self, public, val)

class Edge(BaseModel):
    name: str
    node_b: 'Node'
    node_a: 'Node'
    
    def __init__(self, name, node_a, node_b):
        self.name = name
        self.node_a = node_a
        self.node_b = node_b

class NodeType(Enum):
    UNDEFINED = 0

class Node(BaseModel):
    name: str = ""
    alias: str = ""
    node_type: Optional[NodeType] = None
    parent: 'Node' = None
    id: uuid4 = None
    edges: list[Edge] = None
    
    def __init__(self, name:str, alias:str=None, id: str | UUID=None):
        self.name = name
        
        _alias = alias
        if not _alias:
            _alias = generate_name_alias(name)
        self.alias = _alias
        
        _id = id
        if id and isinstance(id,str):
            UUID(id)
        else:
            _id = uuid4()
        self.id = _id
    
    def as_dict(self):
        return {
            k: (v.id if isinstance(v, Node) and k == 'parent' else v)
            for k, v in self.__dict__.items()
            if not k.startswith('_')
        }

    def as_csv(self):
        return list(self.as_dict().values())

    def csv_headers(self):
        return list(self.as_dict().keys())

class Graph(BaseModel):
    nodes: list[Node]
    edges: list[Edge]
    
    def __init__(self):
        self.nodes: list[Node] = []
        self.edges: list[Edge] = []

    def add_node(self, node: Node):
        self.nodes.append(node)

    def add_edge(self, edge: Edge):
        self.edges.append(edge)

    def get_node_by_id(self, node_id: str | UUID) -> Optional[Node]:
        node_id = str(node_id)
        for node in self.nodes:
            if str(node.id) == node_id:
                return node
        return None
    
    def get_node_by_alias(self, node_alias: str) -> Optional[Node]:
        for node in self.nodes:
            if str(node.alias) == node_alias:
                return node
        return None
    
    def get_node_by_name(self, node_name: str) -> Optional[Node]:
        for node in self.nodes:
            if node_name == node.name:
                return node
        return None
    
    def get_closest_nodes_alias(self, alias: str) -> Optional[Node]:
        possible_nodes = []
        for node in self.nodes:
            if alias in node.alias:
                possible_nodes.append(node)
            if alias == node.alias:
                return node
        return possible_nodes
    
    def match_closest_node_alias(self, alias: str) -> Optional[Node]:
        possible_node = self.get_closest_nodes_alias(alias)
        if isinstance(possible_node, Node):
            if possible_node.alias == alias:
                return possible_node
    
        best_match = None
        highest_similarity = 0
        
        for node in self.nodes:
            similarity = difflib.SequenceMatcher(None, alias, node.alias).ratio()
            if similarity > highest_similarity:
                highest_similarity = similarity
                best_match = node

        return best_match
    
    def get_closest_nodes_name(self, node_name: str) -> Optional[Node]:
        possible_nodes = []
        for node in self.nodes:
            if node_name in node.name:
                possible_nodes.append(node)
            if node_name == node.name:
                return node
        return possible_nodes
        
    def match_closest_node_name(self, node_name: str) -> Optional[Node]:
        # First check for exact match
        for node in self.nodes:
            if node_name == node.name:
                return node

        # Otherwise, find the node with the highest similarity
        best_match = None
        highest_similarity = 0

        for node in self.nodes:
            similarity = difflib.SequenceMatcher(None, node_name, node.name).ratio()
            if similarity > highest_similarity:
                highest_similarity = similarity
                best_match = node

        return best_match

    def match_closest_node_id(self, node_id: str) -> Optional[Node]:
        # Exact match
        for node in self.nodes:
            if node.id == node_id:
                return node

        # Prefix match
        prefix_matches = [node for node in self.nodes if node.id.startswith(node_id)]
        if prefix_matches:
            # If multiple, return shortest match
            return min(prefix_matches, key=lambda n: len(n.id))

        # Fuzzy fallback (optional, or skip)
        best_match = None
        highest_similarity = 0
        for node in self.nodes:
            similarity = difflib.SequenceMatcher(None, node_id, node.id).ratio()
            if similarity > highest_similarity:
                highest_similarity = similarity
                best_match = node

        return best_match

    def get_parent(self, node_id: str | UUID) -> Optional[Node]:
        node = self.get_node_by_id(node_id)
        return node.parent if node else None

    def get_children(self, parent_node: Node) -> list[Node]:
        return [n for n in self.nodes if n.parent == parent_node]

    def get_edges_from(self, node: Node) -> list[Edge]:
        return [e for e in self.edges if e.node_a == node]

    def get_edges_to(self, node: Node) -> list[Edge]:
        return [e for e in self.edges if e.node_b == node]

    def remove_node(self, node: Node):
        # Remove edges connected to the node
        self.edges = [e for e in self.edges if e.node_a != node and e.node_b != node]
        
        # Remove the node itself
        self.nodes = [n for n in self.nodes if n != node]

    def print_graph(self):
        print("Graph Nodes:")
        for node in self.nodes:
            print(f"  - {node.name} ({node.alias}) [{node.id}]")

        print("\nGraph Edges:")
        for edge in self.edges:
            print(f"  - {edge.node_a.alias} --[{edge.name}]--> {edge.node_b.alias}")
    
    def csv_nodes(self) -> list[list]:
        header = []
        csv = []
        
        for node in self.nodes:
            if not header:
                header = node.csv_headers()
            csv.append(node.as_csv())
        
        return csv, header
    
    def save(self, filepath: str):
        with open(filepath, "w") as f:
            f.write(jsonpickle.encode(self))
    
    @staticmethod
    def load(filepath: str) -> 'Graph':
        with open(filepath, "r") as f:
            decoded = jsonpickle.decode(f.read())
        return decoded