"""ai module (Phase 2) — local LLM agent over the service layer.

Tools = thin wrappers over module services; the agent runs as the calling user
so permissions are inherited (DESIGN §8.3). Runtime = Ollama (llm.py)."""
from .registry import registry
from .tools_builtin import register_builtin_tools

register_builtin_tools(registry)
