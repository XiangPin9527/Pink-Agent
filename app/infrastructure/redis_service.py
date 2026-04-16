from typing import Optional, Any
import orjson

from app.infrastructure.redis_client import get_redis
from app.utils.logger import get_logger

logger = get_logger(__name__)

CHECKPOINT_TTL_SECONDS = 3 * 24 * 60 * 60


USER_INSTRUCTION_TTL_SECONDS = 7 * 24 * 60 * 60


class RedisService:
    REDIS_KEY_SUMMARY_PREFIX = "stm_summary"
    REDIS_KEY_MSG_COUNT_PREFIX = "stm_msg_count"
    REDIS_KEY_LAST_COMPRESS_IDX_PREFIX = "stm_last_compress_idx"
    REDIS_KEY_LTM_LAST_EXTRACT_PREFIX = "ltm_last_extract"
    REDIS_KEY_CP_PREFIX = "cp"
    REDIS_KEY_CP_IDS_PREFIX = "cp_ids"
    REDIS_KEY_UI_PREFIX = "ui"

    def _get_summary_key(self, session_id: str) -> str:
        return f"{self.REDIS_KEY_SUMMARY_PREFIX}:{session_id}"

    def _get_msg_count_key(self, session_id: str) -> str:
        return f"{self.REDIS_KEY_MSG_COUNT_PREFIX}:{session_id}"

    def _get_last_compress_idx_key(self, session_id: str) -> str:
        return f"{self.REDIS_KEY_LAST_COMPRESS_IDX_PREFIX}:{session_id}"

    def _get_ltm_extract_key(self, thread_id: str) -> str:
        return f"{self.REDIS_KEY_LTM_LAST_EXTRACT_PREFIX}:{thread_id}"

    def _get_cp_key(self, thread_id: str, ns: str = "", checkpoint_id: str = "") -> str:
        if checkpoint_id:
            return f"{self.REDIS_KEY_CP_PREFIX}:{thread_id}:{ns}:{checkpoint_id}"
        return f"{self.REDIS_KEY_CP_PREFIX}:{thread_id}:{ns}"

    def _get_cp_ids_key(self, thread_id: str, ns: str = "") -> str:
        return f"{self.REDIS_KEY_CP_IDS_PREFIX}:{thread_id}:{ns}"

    def _get_ui_key(self, user_id: str) -> str:
        return f"{self.REDIS_KEY_UI_PREFIX}:{user_id}"

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

    async def get_last_compress_idx(self, session_id: str) -> int:
        try:
            r = await get_redis()
            idx = await r.get(self._get_last_compress_idx_key(session_id))
            if idx:
                return int(idx) if isinstance(idx, bytes) else int(idx)
            return 0
        except Exception as e:
            logger.warning("获取上次压缩位置失败", session_id=session_id, error=str(e))
            return 0

    async def set_last_compress_idx(self, session_id: str, idx: int) -> bool:
        try:
            r = await get_redis()
            await r.set(self._get_last_compress_idx_key(session_id), str(idx))
            return True
        except Exception as e:
            logger.error("设置上次压缩位置失败", session_id=session_id, error=str(e))
            return False

    async def get_checkpoint_ids(self, thread_id: str, ns: str = "") -> list[str]:
        try:
            r = await get_redis()
            ids_key = self._get_cp_ids_key(thread_id, ns)
            members = await r.smembers(ids_key)
            if members:
                return sorted([m.decode() if isinstance(m, bytes) else m for m in members])
            return []
        except Exception as e:
            logger.warning("获取checkpoint IDs失败", thread_id=thread_id, error=str(e))
            return []

    async def add_checkpoint_id(
        self, thread_id: str, ns: str, checkpoint_id: str
    ) -> bool:
        try:
            r = await get_redis()
            ids_key = self._get_cp_ids_key(thread_id, ns)
            await r.sadd(ids_key, checkpoint_id)
            await r.expire(ids_key, CHECKPOINT_TTL_SECONDS)
            return True
        except Exception as e:
            logger.error("添加checkpoint ID失败", thread_id=thread_id, checkpoint_id=checkpoint_id, error=str(e))
            return False

    async def get_checkpoint_by_id(
        self, thread_id: str, ns: str, checkpoint_id: str
    ) -> Optional[dict]:
        try:
            r = await get_redis()
            key = self._get_cp_key(thread_id, ns, checkpoint_id)
            data = await r.get(key)
            if data:
                raw = data if isinstance(data, str) else data.decode()
                return orjson.loads(raw)
            return None
        except Exception as e:
            logger.warning("获取checkpoint失败", thread_id=thread_id, checkpoint_id=checkpoint_id, error=str(e))
            return None

    async def set_checkpoint_by_id(
        self,
        thread_id: str,
        ns: str,
        checkpoint_id: str,
        payload: dict,
    ) -> bool:
        try:
            r = await get_redis()
            key = self._get_cp_key(thread_id, ns, checkpoint_id)
            await r.set(
                key,
                orjson.dumps(payload).decode("utf-8"),
                ex=CHECKPOINT_TTL_SECONDS,
            )
            return True
        except Exception as e:
            logger.error("设置checkpoint失败", thread_id=thread_id, checkpoint_id=checkpoint_id, error=str(e))
            return False

    async def delete_checkpoint(
        self, thread_id: str, ns: str, checkpoint_id: str
    ) -> bool:
        try:
            r = await get_redis()
            key = self._get_cp_key(thread_id, ns, checkpoint_id)
            await r.delete(key)
            ids_key = self._get_cp_ids_key(thread_id, ns)
            await r.srem(ids_key, checkpoint_id)
            return True
        except Exception as e:
            logger.error("删除checkpoint失败", thread_id=thread_id, checkpoint_id=checkpoint_id, error=str(e))
            return False

    async def get_checkpoint(self, thread_id: str, ns: str = "") -> Optional[dict]:
        try:
            ids = await self.get_checkpoint_ids(thread_id, ns)
            if not ids:
                return None
            latest_id = ids[-1]
            return await self.get_checkpoint_by_id(thread_id, ns, latest_id)
        except Exception as e:
            logger.warning("获取最新checkpoint失败", thread_id=thread_id, error=str(e))
            return None

    async def set_checkpoint(
        self, thread_id: str, ns: str, checkpoint_id: str, payload: dict
    ) -> bool:
        try:
            await self.set_checkpoint_by_id(thread_id, ns, checkpoint_id, payload)
            await self.add_checkpoint_id(thread_id, ns, checkpoint_id)
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

    async def get_user_instruction(self, user_id: str) -> dict | None:
        try:
            r = await get_redis()
            data = await r.get(self._get_ui_key(user_id))
            if data:
                raw = data if isinstance(data, str) else data.decode()
                return orjson.loads(raw)
            return None
        except Exception as e:
            logger.warning("获取用户指令失败", user_id=user_id, error=str(e))
            return None

    async def set_user_instruction(
        self, user_id: str, content: str, version: int
    ) -> bool:
        try:
            r = await get_redis()
            payload = {
                "content": content,
                "version": version,
            }
            await r.set(
                self._get_ui_key(user_id),
                orjson.dumps(payload).decode("utf-8"),
                ex=USER_INSTRUCTION_TTL_SECONDS,
            )
            return True
        except Exception as e:
            logger.error("设置用户指令失败", user_id=user_id, error=str(e))
            return False

    async def delete_user_instruction(self, user_id: str) -> bool:
        try:
            r = await get_redis()
            await r.delete(self._get_ui_key(user_id))
            return True
        except Exception as e:
            logger.error("删除用户指令失败", user_id=user_id, error=str(e))
            return False

    async def get_user_instruction_ttl(self, user_id: str) -> int:
        try:
            r = await get_redis()
            ttl = await r.ttl(self._get_ui_key(user_id))
            return ttl if ttl > 0 else 0
        except Exception as e:
            logger.warning("获取用户指令TTL失败", user_id=user_id, error=str(e))
            return 0


_redis_service: Optional[RedisService] = None


def get_redis_service() -> RedisService:
    global _redis_service
    if _redis_service is None:
        _redis_service = RedisService()
    return _redis_service
