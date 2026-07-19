"""ToolRegistry — the allow-list dispatch for agent tool calls.

Replaces per-agent if/elif dispatch with a registry the kernel agent loop
drives. Grants are structural: an agent's registry contains exactly the tools
its package was granted, and dispatching any other name returns UNKNOWN_TOOL
without executing anything. Code owns the registry; the model only ever
chooses among what it was given.
"""
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterable, Iterator

from google.genai import types as genai_types

from app.kernel.config import Settings


@dataclass
class ToolContext:
    """Per-run context handed to every tool invocation. `transcript` is the
    agent's deterministic ground-truth record (kernel.agent.AgentTranscript);
    typed loosely here to avoid a circular import."""

    settings: Settings
    transcript: Any
    emit: Callable[[dict], None]
    node: str  # activity-feed lane


@dataclass(frozen=True)
class ToolSpec:
    """One tool an agent may be granted: declaration + implementation."""

    name: str
    description: str
    parameters: genai_types.Schema
    run: Callable[[dict[str, Any], ToolContext], Awaitable[str]]


class ToolRegistry:
    def __init__(self, specs: Iterable[ToolSpec]):
        self._specs: dict[str, ToolSpec] = {}
        for spec in specs:
            if spec.name in self._specs:
                raise ValueError(f"duplicate tool name {spec.name!r}")
            self._specs[spec.name] = spec

    def __iter__(self) -> Iterator[ToolSpec]:
        return iter(self._specs.values())

    def __contains__(self, name: str) -> bool:
        return name in self._specs

    def grant(self, names: Iterable[str]) -> "ToolRegistry":
        """Restricted registry containing only `names`. Unknown names raise —
        a package declaring a grant for a tool that doesn't exist is a
        configuration error, caught at build time, not silently at run time."""
        missing = [n for n in names if n not in self._specs]
        if missing:
            raise KeyError(f"unknown tool grants: {missing}")
        return ToolRegistry(self._specs[n] for n in names)

    def declarations(self) -> genai_types.Tool:
        """The function declarations handed to the model — exactly the
        granted set, nothing else."""
        return genai_types.Tool(
            function_declarations=[
                genai_types.FunctionDeclaration(
                    name=spec.name,
                    description=spec.description,
                    parameters=spec.parameters,
                )
                for spec in self._specs.values()
            ]
        )

    async def dispatch(self, name: str, args: dict[str, Any], ctx: ToolContext) -> str:
        spec = self._specs.get(name)
        if spec is None:
            return f"UNKNOWN_TOOL: {name}"
        return await spec.run(args, ctx)
