# database.py
import re
import difflib
import warnings
import jsonpickle

from typing import Any, Optional, Callable
from pathlib import Path
from uuid import UUID

from .base_models import Node, Edge, BaseModel
from .query import parse_expr, smart_tokenize
from .jpickle_ex import deserialize_phase2, serialize_phase2

class Graph(BaseModel):
    nodes: list[Node]
    edges: list[Edge]
    
    # ─────────────────────────────────────────────
    # Initialization
    # ─────────────────────────────────────────────
    
    def __init__(self, *args, **kwargs):
        self.nodes: list[Node] = []
        self.edges: list[Edge] = []

    # ─────────────────────────────────────────────
    # Node & Edge Management
    # ─────────────────────────────────────────────

    def add_node(self, node: Node):
        self.nodes.append(node)

    def add_edge(self, edge: Edge):
        self.edges.append(edge)
    
    def remove_node(self, node: Node):
        # Remove edges connected to the node
        self.edges = [e for e in self.edges if e.node_a != node and e.node_b != node]
        
        # Remove the node itself
        self.nodes = [n for n in self.nodes if n != node]

    # ─────────────────────────────────────────────
    # Lookup by Identity
    # ─────────────────────────────────────────────

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
    
    # ─────────────────────────────────────────────
    # Fuzzy / Closest Matching
    # ─────────────────────────────────────────────
    
    def get_closest_nodes_alias(self, alias: str) -> Optional[Node]:
        possible_nodes = []
        for node in self.nodes:
            if alias in node.alias:
                possible_nodes.append(node)
            if alias == node.alias:
                return node
        return possible_nodes
    
    def match_closest_node_alias(self, alias: str, match_cutoff: float = 0.7) -> Optional[Node]:
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

        if highest_similarity >= match_cutoff:
            return best_match
        else:
            return None
    
    def get_closest_nodes_name(self, node_name: str) -> Optional[Node]:
        possible_nodes = []
        for node in self.nodes:
            if node_name in node.name:
                possible_nodes.append(node)
            if node_name == node.name:
                return node
        return possible_nodes
        
    def match_closest_node_name(self, node_name: str, match_cutoff: float = 0.7) -> Optional[Node]:
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

        if highest_similarity >= match_cutoff:
            return best_match
        else:
            return None

    def match_closest_node_id(self, node_id: str, match_cutoff: float = 0.7) -> Optional[Node]:
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

        if highest_similarity >= match_cutoff:
            return best_match
        else:
            return None

    # ─────────────────────────────────────────────
    # Graph Relationships
    # ─────────────────────────────────────────────

    def get_parent(self, node_id: str | UUID) -> Optional[Node]:
        node = self.get_node_by_id(node_id)
        return node.parent if node else None

    def get_children(self, parent_node: Node) -> list[Node]:
        return [n for n in self.nodes if n.parent == parent_node]
    
    def get_edges_from(self, node: Node) -> list[Edge]:
        return [e for e in self.edges if e.node_a == node]

    def get_edges_to(self, node: Node) -> list[Edge]:
        return [e for e in self.edges if e.node_b == node]


    # ─────────────────────────────────────────────
    # Filtering / Querying
    # ─────────────────────────────────────────────

    def filter_nodes_by_field(self, field: str, value: Any) -> list[Node]:
        if not all(hasattr(n, field) for n in self.nodes):
            raise AttributeError(f"Field '{field}' not found in Node")
        return [n for n in self.nodes if getattr(n, field, None) == value]

    def find_nodes(self, fn: Callable[['Node'], bool]) -> tuple[list[list], list[str]]:
        return [n for n in self.nodes if fn(n)]

    def find_nodes_by_regex(self, field: str, pattern: str) -> tuple[list[list], list[str]]:
        regex = re.compile(pattern)
        return [n for n in self.nodes if regex.search(str(getattr(n, field, "")))]

    def find_nodes_by_query(self, query: str) -> list[Node]:
        tokens = smart_tokenize(query)
        ast, i = parse_expr(tokens)
        if i != len(tokens):
            raise SyntaxError(f"Unexpected trailing tokens: {tokens[i:]}")
        return [n for n in self.nodes if self._evaluate_ast(ast, n)]

    def _evaluate_ast(self, ast, node) -> bool:
        if isinstance(ast, tuple):
            tag = ast[0]

            if tag == 'MATCH':
                field, op, pattern = ast[1], ast[2], ast[3]
                value = getattr(node, field, None)
                if value is None:
                    return False
                value = str(value)

                try:
                    if op == '=':
                        return re.search(pattern, value) is not None
                    elif op == '!=':
                        return re.search(pattern, value) is None
                    else:
                        raise ValueError(f"Unknown operator: {op}")
                except re.error as e:
                    raise ValueError(f"Invalid regex: {pattern!r} ({e})")

            elif tag == 'or':
                left = self._evaluate_ast(ast[1], node)
                right = self._evaluate_ast(ast[2], node)
                return left or right

            elif tag == 'and':
                left = self._evaluate_ast(ast[1], node)
                right = self._evaluate_ast(ast[2], node)
                return left and right

        return False


    def sort_nodes_by(
        self, field: str, limit: int = None, offset: int = 0
    ) -> tuple[list[list], list[str]]:
        if not all(hasattr(n, field) for n in self.nodes):
            raise AttributeError(f"Field '{field}' not found in Node")

        sorted_nodes = sorted(self.nodes, key=lambda n: getattr(n, field, ""))
        paged_nodes = sorted_nodes[offset: offset + limit if limit is not None else None]

        return paged_nodes

    # ─────────────────────────────────────────────
    # Exporting / Serialization
    # ─────────────────────────────────────────────

    def _nodes_to_csv(self, nodes: list['Node']) -> tuple[list[list], list[str]]:
        if not nodes:
            return [], []
        header = nodes[0].csv_headers()
        data = [n.as_csv() for n in nodes]
        return data, header

    def csv_nodes(self) -> tuple[list[list], list[str]]:
        return self._nodes_to_csv(self.nodes)

    def save(self, filepath: str | Path, raise_empty_nodes_error=False) -> None:
        from json import loads, dumps

        if all(isinstance(x, dict) and not x for x in self.nodes):
            msg = "Node data is likely malformed as the nodes list contains only empty dicts."
            if raise_empty_nodes_error:
                raise(msg)

        # Clean node data
        for i in reversed(range(len(self.nodes))):
            if self.nodes[i] == {}:
                del self.nodes[i]

        filepath = Path(filepath)

        # Prevent writing to a directory
        if filepath.exists() and filepath.is_dir():
            raise ValueError(f"Refusing to save to directory: {filepath}")

        # Ensure parent directories exist
        filepath.parent.mkdir(parents=True, exist_ok=True)

        # Encode graph -> JSON string with refs
        raw_json_str = jsonpickle.encode(self, make_refs=True)

        # Defensive check
        if not raw_json_str or raw_json_str.strip() == "{}":
            raise ValueError("Refusing to save empty or malformed graph data")

        # Convert to dict for phase2 transform
        data_dict = loads(raw_json_str)
        transformed_data = serialize_phase2(data_dict)

        # Write final JSON string to file
        filepath.write_text(dumps(transformed_data, indent=2))
    
    @staticmethod
    def load(filepath: Path, type_overrides: dict[str, str] = {}) -> 'Graph':
        from json import loads, dumps

        if isinstance(filepath, str):
            filepath = Path(filepath)

        # Read file as JSON dict
        raw_data = loads(filepath.read_text())

        if "REGISTRY" in raw_data:
            # Reverse the phase2 transformation
            deserialized_data = deserialize_phase2(raw_data, type_overrides=type_overrides)
            obj = jsonpickle.decode(dumps(deserialized_data), keys=True)
        else:
            # Try to convert legacy structure to 2-phase
            serialized = serialize_phase2(raw_data)
            deserialized_data = deserialize_phase2(serialized, type_overrides=type_overrides)
            obj = jsonpickle.decode(dumps(deserialized_data), keys=True)
        
        return obj
    
    # ─────────────────────────────────────────────
    # Debug / Introspection
    # ─────────────────────────────────────────────
    
    def summary(self):
        return {
            "total_nodes": len(self.nodes),
            "total_edges": len(self.edges),
            "isolated_nodes": len([n for n in self.nodes if not self.get_edges_from(n) and not self.get_edges_to(n)])
        }
    
    def print_graph(self) -> None:
        """MOSTLY FOR DEBUG PURPOSES"""
        print("Graph Nodes:")
        for node in self.nodes:
            print(f"  - {node.name} ({node.alias}) [{node.id}]")

        print("\nGraph Edges:")
        for edge in self.edges:
            print(f"  - {edge.node_a.alias} --[{edge.name}]--> {edge.node_b.alias}")
