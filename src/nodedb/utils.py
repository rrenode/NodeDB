# utils.py
import gc
import sys
import inspect

from typing import Any, Dict, Type
from functools import lru_cache

class AutoPropertiesMeta(type):
    def __new__(cls, name, bases, dct):
        # For every annotated field, pull off any class‐level default
        # and install a private backing field + a public property
        annotations = dct.get("__annotations__", {})
        for attr in annotations:
            default = dct.pop(attr, None)
            dct[f"_{attr}"] = default
            dct[attr] = property(
                lambda self, attr=attr: getattr(self, f"_{attr}", None),
                lambda self, value, attr=attr: setattr(self, f"_{attr}", value)
            )
        return super().__new__(cls, name, bases, dct)


class OldVariableNamesMeta(AutoPropertiesMeta):
    def __new__(cls, name, bases, dct):
        original_init = dct.get("__init__")
        old_map = dct.get("__old_mappings__", {})

        # 1) Wrap __init__ to remap old-kwargs -> new-attrs on construction
        def new_init(self, *args, **kwargs):
            extra: Dict[str, Any] = {}
            for old, new in old_map.items():
                if old in kwargs:
                    extra[new] = kwargs.pop(old)

            if original_init:
                original_init(self, *args, **kwargs)
            else:
                for base in bases:
                    bi = getattr(base, "__init__", None)
                    if bi:
                        bi(self, *args, **kwargs)
                        break

            for new, val in extra.items():
                setattr(self, new, val)

        dct["__init__"] = new_init

        # 2) Install proxy properties so .old_name ↔ .new_name
        def make_proxy(old, new):
            return property(
                lambda self: getattr(self, new),
                lambda self, v: setattr(self, new, v)
            )
        for old, new in old_map.items():
            dct[old] = make_proxy(old, new)

        # 3) Ensure pickle/jsonpickle will call your __getstate__/__setstate__
        #    by overriding __reduce__ to return (cls, (), state_dict)
        #def __reduce__(self):
        #    return (self.__class__, (), self.__getstate__())
        #dct["__reduce__"] = __reduce__

        return super().__new__(cls, name, bases, dct)

def handle_old_variable_names(cls):
    original_init = cls.__init__

    def new_init(self, *args, **kwargs):
        # Apply old-to-new variable name mapping during instantiation
        old_mappings = getattr(cls, "__old_mappings__", {})
        for old_attr, new_attr in old_mappings.items():
            if old_attr in kwargs:
                kwargs[new_attr] = kwargs.pop(old_attr)  # Remap old attribute to new one
        original_init(self, *args, **kwargs)

    cls.__init__ = new_init

    # Add property behavior for the old variable names to point to the new ones
    def add_old_name_property(attr, new_attr):
        def getter(self):
            return getattr(self, new_attr, None)  # Return the value of the new attribute

        def setter(self, value):
            setattr(self, new_attr, value)  # Set the value for the new attribute

        return property(getter, setter)

    # Check for old mappings and add properties for them
    old_mappings = getattr(cls, "__old_mappings__", {})
    for old_attr, new_attr in old_mappings.items():
        setattr(cls, old_attr, add_old_name_property(old_attr, new_attr))

    return cls

def auto_properties(cls):
    # Loop through the class annotations to get the attributes
    for attr, value in cls.__annotations__.items():
        # Skip special methods and private attributes
        if not hasattr(cls, attr):  # If the attribute is not already defined as a method or other property
            # Create a private attribute and define the property
            setattr(cls, f"_{attr}", None)  # Initialize a private attribute
            
            # Create getter and setter
            setattr(cls, attr, property(
                lambda self, attr=attr: getattr(self, f"_{attr}", None),  # Getter
                lambda self, value, attr=attr: setattr(self, f"_{attr}", value)  # Setter
            ))

    return cls

def generate_name_alias(name: str, min_length:int = 3, max_length: int = 3, forced_length: int = 0) -> str:
    """
    Generates a short alias from a given name by using the initials and truncating it to the desired length.
    
    Args:
        name (str): The original name (e.g., "todo_app").
        min_length (int): The minimum length of the alias (default is 3 characters).
        max_length (int): The maximum length of the alias (default is 3 characters).
        forced_length (int): Unused.
    
    Returns:
        str: The generated alias.
    """
    name = name.lower()
    if '_' in name:
        words = name.split('_')
    elif ' ' in name:
        words = name.split(' ')
    else:
        words = [name]  # fallback if no separators

    alias = ''.join([word[0] for word in words if word])

    # If alias is too short, continue adding more letters from words
    if len(alias) < min_length:
        for word in words:
            i = 1  # start after first letter
            while len(alias) < min_length and i < len(word):
                alias += word[i]
                i += 1

    return alias[:max_length]  # cut off at max_length

def recurse_json(obj, callback):
    """
    Recursively walk a JSON-like structure, applying `callback` to every dict.
    """
    if isinstance(obj, dict):
        result = callback(obj)

        # If callback changed the object to something non-dict, stop recursion
        if not isinstance(result, dict):
            return result

        for key in list(result.keys()):
            result[key] = recurse_json(result[key], callback)
        return result

    elif isinstance(obj, list):
        return [recurse_json(item, callback) for item in obj]

    else:
        # Primitive (str, int, None, etc.) – return as-is
        return obj

def get_all_loaded_classes(clear_cache=False):
    if clear_cache:
        __get_all_loaded_classes__.cache_clear()
    return __get_all_loaded_classes__

@lru_cache(1)
def __get_all_loaded_classes__():
    return [obj for obj in gc.get_objects() if isinstance(obj, type)]

def get_all_classes_from_specific_loaded_module(module_namespace:str, clear_cache=False):
    """
    Filters loaded classes from modules that start with a given namespace (e.g., 'userlib').
    Returns a dict in the format {cls_import_path: cls_obj}.
    Interface for a function with a simialar name for easy cache clear.
    """
    if clear_cache:
        __get_all_classes_from_specific_loaded_module__.cache_clear()
    return __get_all_classes_from_specific_loaded_module__(module_namespace)

@lru_cache(1)
def __get_all_classes_from_specific_loaded_module__(module_namespace: str, clear_cache: bool = False):
    """
    Filters loaded classes from modules that start with a given namespace (e.g., 'userlib').
    Returns a dict in the format {cls_import_path: cls_obj}.
    """
    all_classes = get_all_classes_from_loaded_modules(clear_cache=clear_cache)

    return {
        path: cls
        for path, cls in all_classes.items()
        if cls.__module__.startswith(module_namespace)
    }

def get_all_classes_from_loaded_modules(clear_cache=False):
    """Gets all classes and returns a dict in the format {cls_import_path:cls_obj}
    Interface for a function with a simialar name for easy cache clear.
    """
    if clear_cache:
        __get_all_classes_from_loaded_modules__.cache_clear()
    return __get_all_classes_from_loaded_modules__()

@lru_cache(maxsize=1)
def __get_all_classes_from_loaded_modules__():
    """Gets all classes and returns a dict in the format {cls_import_path:cls_obj}
    Uses lru_cache with max_size = 1.
    Use cache_clear to force a clear.
    """
    classes = {}
    for module in list(sys.modules.values()):
        if module and hasattr(module, "__dict__"):
            for name, obj in module.__dict__.items():
                if inspect.isclass(obj):
                    full_path = f"{obj.__module__}.{obj.__qualname__}"
                    classes[full_path] = obj
    return classes

def get_all_subclasses_of(base_cls: Type) -> Dict[str, Type]:
    """
    Returns a dictionary of {full_class_path: class_obj}
    for all currently loaded classes that inherit from `base_cls`.
    """
    from . import get_all_classes_from_loaded_modules  # if inside utils.py

    all_classes = get_all_classes_from_loaded_modules()

    return {
        path: cls
        for path, cls in all_classes.items()
        if inspect.isclass(cls) and issubclass(cls, base_cls) and cls is not base_cls
    }