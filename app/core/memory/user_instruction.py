from typing import Optional

from app.utils.logger import get_logger
from app.infrastructure.redis_service import get_redis_service
from app.infrastructure.db_service import get_db_service

logger = get_logger(__name__)

USER_INSTRUCTION_TEMPLATE = """
## 用户个性化约束（严格遵守）

{user_instruction}

---
以上是用户对该次对话的个性化约束，请严格按照上述约束生成回复。
"""


class UserInstructionService:
    """
    用户指令服务

    缓存策略：
    1. 先查 Redis（快速）
    2. Redis 未命中/过期 → 查 DB
    3. DB 命中 → 回填 Redis（TTL 7天）
    4. 都未命中 → 返回空字符串
    """

    def __init__(self):
        self._redis = get_redis_service()
        self._db = get_db_service()

    async def get(self, user_id: str) -> str:
        """获取用户指令内容"""
        if not user_id:
            return ""

        try:
            redis_data = await self._redis.get_user_instruction(user_id)
            if redis_data:
                content = redis_data.get("content", "")
                logger.debug("从 Redis 获取用户指令", user_id=user_id)
                return content
        except Exception as e:
            logger.warning("从 Redis 获取用户指令失败，回退到 DB", user_id=user_id, error=str(e))

        try:
            db_data = await self._db.get_user_instruction(user_id)
            if db_data:
                content = db_data.get("content", "")
                version = db_data.get("version", 1)
                await self._redis.set_user_instruction(user_id, content, version)
                logger.debug("从 DB 获取并回填 Redis", user_id=user_id)
                return content
        except Exception as e:
            logger.error("从 DB 获取用户指令失败", user_id=user_id, error=str(e))

        return ""

    async def save(self, user_id: str, content: str) -> bool:
        """保存用户指令（双写 Redis + DB）"""
        if not user_id or not content:
            logger.warning("保存用户指令失败：参数为空", user_id=user_id)
            return False

        content = content.strip()
        version = 1

        try:
            existing = await self._db.get_user_instruction(user_id)
            if existing:
                version = existing.get("version", 1) + 1
        except Exception as e:
            logger.warning("获取现有版本号失败", user_id=user_id, error=str(e))

        redis_success = False
        try:
            redis_success = await self._redis.set_user_instruction(user_id, content, version)
            logger.debug("用户指令已写入 Redis", user_id=user_id, version=version)
        except Exception as e:
            logger.warning("写入 Redis 失败，降级到 DB", user_id=user_id, error=str(e))

        db_success = False
        try:
            db_success = await self._db.save_user_instruction(user_id, content, version)
            logger.debug("用户指令已写入 DB", user_id=user_id, version=version)
        except Exception as e:
            logger.error("写入 DB 失败", user_id=user_id, error=str(e))
            return False

        return redis_success or db_success

    async def delete(self, user_id: str) -> bool:
        """删除用户指令"""
        if not user_id:
            return False

        redis_success = False
        try:
            redis_success = await self._redis.delete_user_instruction(user_id)
            logger.debug("用户指令已从 Redis 删除", user_id=user_id)
        except Exception as e:
            logger.warning("从 Redis 删除失败", user_id=user_id, error=str(e))

        db_success = False
        try:
            db_success = await self._db.delete_user_instruction(user_id)
            logger.debug("用户指令已从 DB 删除", user_id=user_id)
        except Exception as e:
            logger.error("从 DB 删除失败", user_id=user_id, error=str(e))
            return False

        return redis_success or db_success

    async def exists(self, user_id: str) -> bool:
        """检查用户是否有自定义指令"""
        if not user_id:
            return False

        instruction = await self.get(user_id)
        return bool(instruction and instruction.strip())

    def format_for_system_prompt(self, user_instruction: str) -> str:
        """格式化用户指令，生成系统提示片段"""
        if not user_instruction or not user_instruction.strip():
            return ""
        return USER_INSTRUCTION_TEMPLATE.format(user_instruction=user_instruction.strip())


_user_instruction_service: Optional[UserInstructionService] = None


def get_user_instruction_service() -> UserInstructionService:
    """获取用户指令服务单例"""
    global _user_instruction_service
    if _user_instruction_service is None:
        _user_instruction_service = UserInstructionService()
    return _user_instruction_service


async def get_user_instruction(user_id: str) -> str:
    """快捷函数：获取用户指令内容"""
    service = get_user_instruction_service()
    return await service.get(user_id)


async def save_user_instruction(user_id: str, content: str) -> bool:
    """快捷函数：保存用户指令"""
    service = get_user_instruction_service()
    return await service.save(user_id, content)


async def delete_user_instruction(user_id: str) -> bool:
    """快捷函数：删除用户指令"""
    service = get_user_instruction_service()
    return await service.delete(user_id)


__all__ = [
    "UserInstructionService",
    "get_user_instruction_service",
    "get_user_instruction",
    "save_user_instruction",
    "delete_user_instruction",
    "USER_INSTRUCTION_TEMPLATE",
]
