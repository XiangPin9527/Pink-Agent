from fastapi import APIRouter

from app.api.v1 import agent, rag, health, user_instruction

api_router = APIRouter()

api_router.include_router(health.router, prefix="/v1", tags=["health"])
api_router.include_router(agent.router, prefix="/v1/agent", tags=["agent"])
api_router.include_router(rag.router, prefix="/v1/rag", tags=["rag"])
api_router.include_router(user_instruction.router, prefix="/v1/user/instruction", tags=["user_instruction"])

"""
这段代码的作用是做路由，将不同的请求路由到不同的节点进行处理
"""