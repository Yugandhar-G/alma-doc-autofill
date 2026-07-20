"""WorkflowPackage — the contract a legal-domain package exports to run on
the kernel.

"Install as data": a package is a manifest + a state model + a graph builder
+ (optionally) its own HTTP surface, tool grants, and eval kit. Installing
one means adding it to app.registry.INSTALLED_PACKAGES — engine code never
changes. Phase-B1 scope: manifest/state/build_graph/router are live;
tool_grants and eval_kit become load-bearing in B2 (eval harness) and D1
(firm-data grants); full GraphDeps injection lands with the matter store.
"""
from dataclasses import dataclass, field
from typing import Any, Callable

from fastapi import APIRouter
from pydantic import BaseModel


@dataclass(frozen=True)
class StageSpec:
    """One display stage: graph node ids grouped under a human label — drives
    the frontend stage checklist from the manifest instead of hardcoded names."""

    id: str
    label: str
    nodes: tuple[str, ...] = ()


@dataclass(frozen=True)
class PackageManifest:
    package_id: str
    version: str
    title: str
    description: str = ""
    matter_types: tuple[str, ...] = ()
    stages: tuple[StageSpec, ...] = ()
    interrupt_kinds: tuple[str, ...] = ()

    def summary(self) -> dict[str, Any]:
        """The wire form for GET /api/packages."""
        return {
            "package_id": self.package_id,
            "version": self.version,
            "title": self.title,
            "description": self.description,
            "matter_types": list(self.matter_types),
            "stages": [
                {"id": s.id, "label": s.label, "nodes": list(s.nodes)} for s in self.stages
            ],
            "interrupt_kinds": list(self.interrupt_kinds),
        }


@dataclass(frozen=True)
class WorkflowPackage:
    """What a package exports. build_graph(checkpointer=...) must compile the
    package's deterministic graph — same seam the screener has always had."""

    manifest: PackageManifest
    state_model: type[BaseModel]
    build_graph: Callable[..., Any]
    router_factory: Callable[[], APIRouter] | None = None
    tool_grants: frozenset[str] = frozenset()
    eval_kit: Any | None = None
    knowledge: Any | None = None
    field_maps: dict[str, Any] = field(default_factory=dict)
