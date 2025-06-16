from enum import Enum
from uuid import uuid4, UUID
from typing import Any, Dict, Optional

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
        1. Rename any old -> new keys
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

class BaseModelTypes(Enum):
    NONE = 0
    BASEMODEL = 1
    NODE = 2
    EDGE = 3
    
    @classmethod
    def get_type(cls, model_key):
        match model_key:
            case "NONE":
                return None
            case "BASEMODEL":
                return BaseModel
            case "NODE":
                return Node
            case "EDGE":
                return Edge