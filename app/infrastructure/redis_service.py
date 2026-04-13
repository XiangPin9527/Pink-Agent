from typing import Optional, Any
import orjson

from app.infrastructure.redis_client import get_redis
from app.utils.logger import get_logger

logger = get_logger(__name__)


class RedisService:
    REDIS_KEY_SUMMARY_PREFIX = "stm_summary"
    REDIS_KEY_MSG_COUNT_PREFIX = "stm_msg_count"
    REDIS_KEY_LTM_LAST_EXTRACT_PREFIX = "ltm_last_extract"
    REDIS_KEY_CP_PREFIX = "cp"

    def _get_summary_key(self, session_id: str) -> str:
        return f"{self.REDIS_KEY_SUMMARY_PREFIX}:{session_id}"

    def _get_msg_count_key(self, session_id: str) -> str:
        return f"{self.REDIS_KEY_MSG_COUNT_PREFIX}:{session_id}"

    def _get_ltm_extract_key(self, thread_id: str) -> str:
        return f"{self.REDIS_KEY_LTM_LAST_EXTRACT_PREFIX}:{thread_id}"

    def _get_cp_key(self, thread_id: str, ns: str = "") -> str:
        return f"{self.REDIS_KEY_CP_PREFIX}:{thread_id}:{ns}"

    async def get_short_term_summary(self, session_id: str) -> str:
        try:
            r = await get_redis()
            summary = await r.get(self._get_summary_key(session_id))
            if summary:
                return summary.decode() if isinstance(summary, bytes) else summary
            return ""
        except Exception as e:
            logger.warning("获取短期记忆摘要失败", session_id=session_id, error=str(e))
            return ""

    async def set_short_term_summary(self, session_id: str, summary: str) -> bool:
        try:
            r = await get_redis()
            await r.set(self._get_summary_key(session_id), summary)
            return True
        except Exception as e:
            logger.error("更新短期记忆摘要失败", session_id=session_id, error=str(e))
            return False

    async def get_msg_count(self, session_id: str) -> int:
        try:
            r = await get_redis()
            count = await r.get(self._get_msg_count_key(session_id))
            if count:
                return int(count) if isinstance(count, bytes) else int(count)
            return 0
        except Exception as e:
            logger.warning("获取消息计数失败", session_id=session_id, error=str(e))
            return 0

    async def set_msg_count(self, session_id: str, count: int) -> bool:
        try:
            r = await get_redis()
            await r.set(self._get_msg_count_key(session_id), count)
            return True
        except Exception as e:
            logger.error("设置消息计数失败", session_id=session_id, error=str(e))
            return False

    async def increment_msg_count(self, session_id: str) -> int:
        try:
            r = await get_redis()
            new_count = await r.incr(self._get_msg_count_key(session_id))
            return int(new_count)
        except Exception as e:
            logger.error("递增消息计数失败", session_id=session_id, error=str(e))
            return 0

    async def get_checkpoint(self, thread_id: str, ns: str = "") -> Optional[dict]:
        try:
            r = await get_redis()
            data = await r.get(self._get_cp_key(thread_id, ns))
            if data:
                raw = data if isinstance(data, str) else data.decode()
                return orjson.loads(raw)
            return None
        except Exception as e:
            logger.warning("获取checkpoint失败", thread_id=thread_id, error=str(e))
            return None

    async def set_checkpoint(self, thread_id: str, ns: str, payload: dict) -> bool:
        try:
            r = await get_redis()
            await r.set(self._get_cp_key(thread_id, ns), orjson.dumps(payload).decode("utf-8"))
            return True
        except Exception as e:
            logger.error("设置checkpoint失败", thread_id=thread_id, error=str(e))
            return False

    async def get_longterm_extract_position(self, thread_id: str) -> int:
        try:
            r = await get_redis()
            pos = await r.get(self._get_ltm_extract_key(thread_id))
            if pos:
                return int(pos) if isinstance(pos, bytes) else int(pos)
            return 0
        except Exception as e:
            logger.warning("获取长期记忆提取位置失败", thread_id=thread_id, error=str(e))
            return 0

    async def set_longterm_extract_position(self, thread_id: str, position: int) -> bool:
        try:
            r = await get_redis()
            await r.set(self._get_ltm_extract_key(thread_id), str(position))
            return True
        except Exception as e:
            logger.error("设置长期记忆提取位置失败", thread_id=thread_id, error=str(e))
            return False

    REDIS_KEY_RAG_TASK_PREFIX = "rag_task"

    def _get_rag_task_key(self, task_id: str) -> str:
        return f"{self.REDIS_KEY_RAG_TASK_PREFIX}:{task_id}"

    async def set_rag_task_status(
        self, task_id: str, status: str, result: dict | None = None
    ) -> bool:
        try:
            r = await get_redis()
            payload = {"status": status}
            if result:
                payload["result"] = result
            await r.set(
                self._get_rag_task_key(task_id),
                orjson.dumps(payload).decode("utf-8"),
                ex=86400,
            )
            return True
        except Exception as e:
            logger.error("设置RAG任务状态失败", task_id=task_id, error=str(e))
            return False

    async def get_rag_task_status(self, task_id: str) -> dict | None:
        try:
            r = await get_redis()
            data = await r.get(self._get_rag_task_key(task_id))
            if data:
                raw = data if isinstance(data, str) else data.decode()
                return orjson.loads(raw)
            return None
        except Exception as e:
            logger.warning("获取RAG任务状态失败", task_id=task_id, error=str(e))
            return None


_redis_service: Optional[RedisService] = None


def get_redis_service() -> RedisService:
    global _redis_service
    if _redis_service is None:
        _redis_service = RedisService()
    return _redis_service
