from uuid import uuid4
from typing import Optional
from difflib import get_close_matches

import warnings

from .utils import (
    recurse_json, 
    get_all_classes_from_loaded_modules,
    get_all_classes_from_specific_loaded_module,
    get_all_subclasses_of
    )
from .base_models import Node, Edge, BaseModel, BaseModelTypes

def fuzzy_type_match(type_path: str, known_types: dict[str, type]) -> Optional[str]:
    close = get_close_matches(type_path, known_types.keys(), n=1, cutoff=0.7)
    return close[0] if close else None

def find_type_fallback(type_path: str, base_model: type[BaseModel]) -> Optional[str]:
    # First use the base model to see if anything that extends that type has a close name
    inherited_classes = get_all_subclasses_of(base_model)
    interited_attempt = fuzzy_type_match(type_path, inherited_classes)
    
    if interited_attempt:
        return interited_attempt
    
    # If none, then we extend to all in the namespace
    module = type_path.split(".")[0]
    namespace_classes = get_all_classes_from_specific_loaded_module(module)
    namespace_attempt = fuzzy_type_match(type_path, namespace_classes)
    
    if namespace_attempt:
        return namespace_attempt

def resolve_class_type(import_path: str) -> Optional[type]:
    import importlib

    try:
        module_path, _, class_name = import_path.rpartition(".")
        module = importlib.import_module(module_path)
        return getattr(module, class_name)
    except Exception:
        return None

def deserialize_phase2(data, type_overrides: dict[str, str] = {}, strict=False) -> dict:
    """
    Replaces all "py/object" UUID tags with their original values from the REGISTRY.
    Modifies in-place and removes the REGISTRY entry.
    """
    registry = data.pop("REGISTRY", {})

    def callback(d: dict):
        if "py/object" in d:
            uid = d["py/object"]
            if isinstance(uid, str) and uid.startswith("EXTRACT_") and uid in registry:
                obj_path = registry[uid]["path"]
                base_model_key = registry[uid]["base"]
                base_model = BaseModelTypes.get_type(base_model_key)
                possible_classes = get_all_classes_from_loaded_modules()
                if obj_path not in possible_classes.keys() and obj_path not in type_overrides.keys():
                    attempt = find_type_fallback(obj_path, base_model=base_model)
                    fuzzy_fail_msg =  f"The object `{obj_path}` could not be found.\n" \
                            "Fuzzy matching could also not find a replace that was similar enough."
                    if attempt:
                        warnings.warn(f"Fuzzy matched `{obj_path}` to `{attempt}`")
                        obj_path = attempt
                    else:
                        if strict:
                            raise ValueError(fuzzy_fail_msg)
                        else:
                            warnings.warn(fuzzy_fail_msg)
                obj_path = type_overrides.get(obj_path, obj_path)
                d["py/object"] = obj_path
        return d

    return recurse_json(data, callback)

def serialize_phase2(data):
    """
    Replace all "py/object" strings with unique UUID tags, storing original values in a registry.
    Returns (transformed_data, registry)
    """

    registry = {}        # maps UUID -> original "py/object" path
    reverse = {}         # maps "py/object" path -> UUID (for deduplication)

    def callback(d: dict):
        if "py/object" in d:
            original = d["py/object"]
            if original in reverse:
                uid = reverse[original]
            else:
                cls = resolve_class_type(original)
                model_type = None
                if cls:
                    if issubclass(cls, Node):
                        model_type = BaseModelTypes.NODE
                    elif issubclass(cls, Edge):
                        model_type = BaseModelTypes.EDGE
                    elif issubclass(cls, BaseModel):
                        model_type = BaseModelTypes.BASEMODEL
                    else:
                        #TODO: Maybe this should through an error?
                        model_type = BaseModelTypes.NODE
                uid = "EXTRACT_" + str(uuid4())
                reverse[original] = uid
                registry[uid] = {"path": original, "base": model_type.name}

            d["py/object"] = uid

        return d

    new_data = recurse_json(data, callback)
    new_data["REGISTRY"] = registry
    return new_data