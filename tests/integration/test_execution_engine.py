"""Integration tests for ExecutionEngine with REST adapter."""

import pytest
from agent_eval import ExecutionEngine, get_registry


@pytest.mark.asyncio
async def test_execution_engine_initialization():
    """Test that execution engine initializes correctly."""
    engine = ExecutionEngine()
    assert engine is not None
    assert engine.adapter_registry is not None
    assert engine.trace_collector is not None


@pytest.mark.asyncio
async def test_adapter_registry_has_rest():
    """Test that REST adapter is auto-registered."""
    registry = get_registry()
    assert registry.has_adapter("rest")


@pytest.mark.asyncio
async def test_list_adapters():
    """Test listing available adapters."""
    engine = ExecutionEngine()
    adapters = engine.list_adapters()
    assert "rest" in adapters


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
