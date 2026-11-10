"""Reglas automáticas para conservar la dirección de dependencias."""

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).parents[1] / "src" / "parkingpro"


def _imports_in(directory: Path) -> set[str]:
    imports: set[str] = set()
    for source_file in directory.rglob("*.py"):
        tree = ast.parse(source_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
    return imports


def _assert_layer_does_not_import(layer: str, forbidden_layers: set[str]) -> None:
    imports = _imports_in(PACKAGE_ROOT / layer)
    forbidden = {
        imported
        for imported in imports
        if any(imported.startswith(f"parkingpro.{name}") for name in forbidden_layers)
    }
    assert forbidden == set()


def test_domain_is_independent():
    _assert_layer_does_not_import(
        "domain",
        {"application", "infrastructure", "presentation"},
    )


def test_application_does_not_depend_on_adapters():
    _assert_layer_does_not_import(
        "application",
        {"infrastructure", "presentation"},
    )


def test_presentation_uses_application_not_infrastructure():
    _assert_layer_does_not_import("presentation", {"infrastructure"})


def test_infrastructure_does_not_depend_on_presentation():
    _assert_layer_does_not_import("infrastructure", {"presentation"})
