"""Local Vera identity/bootstrap resource package."""

from .loader import load_json_resource, load_text_resource, resource_path

__all__ = ["load_json_resource", "load_text_resource", "resource_path"]
