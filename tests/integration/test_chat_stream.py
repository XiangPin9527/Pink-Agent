"""
测试流式对话接口
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_chat_stream(client: AsyncClient):
    """测试流式对话接口"""
    response = await client.post(
        "/v1/agent/chat/stream",
        json={
            "user_id": "test_user",
            "session_id": "test_session",
            "agent_id": "test_agent",
            "message": "你好",
            "max_step": 3,
        },
    )

    assert response.status_code == 200
