"""Обратная совместимость — используйте core.llm_client."""

from core.llm_client import LLMClient, create_llm_client

GrokClient = LLMClient

__all__ = ["GrokClient", "LLMClient", "create_llm_client"]
