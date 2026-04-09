from typing import Any

from langchain_core.language_models import BaseChatModel
from langgraph.store.base import BaseStore

from app.utils.logger import get_logger

logger = get_logger(__name__)

LONGTERM_EXTRACT_INTERVAL = 10

EXTRACT_SYSTEM_PROMPT = """# ROLE
你是一个极其严谨的「AI 记忆中枢系统」。你的任务是监控用户的对话，从中提取、更新或删除属于「长期高价值」的实体记忆，并忽略所有短期、瞬时、闲聊的内容。

# EXTRACTION PRINCIPLES (宁缺毋滥原则)
1. 区分长短期：忽略具体的一次性任务（如"帮我写段代码"、"翻译这句话"）、临时情绪或礼貌用语。
2. 捕获变更：如果用户表达了偏好的改变或事实的更正，必须输出对应的覆写/更新意图。
3. 保持原子性：每条记忆应独立完整，包含足够的上下文。不要写“决定用Redis”，应写“在电商项目中决定使用Redis做高并发缓存”。

# MEMORY CATEGORIES
- `profile`: 用户的基本事实（职业、身份、教育背景、常驻地）
- `preference`: 长期偏好与习惯（代码风格、沟通语气、喜欢的工具/语言、忌讳）
- `project`: 长期目标与正在推进的项目事实（项目名称、技术栈、核心决策）
- `relation`: 用户提到的人际关系（同事、导师、亲友）

# OUTPUT SCHEMA
请严格输出一个 JSON 数组。数组中的每个对象代表一条记忆操作：
```json
[
  {"category": "preference", "content": "用户偏好使用Python进行开发"},
  {"category": "background", "content": "用户是一名后端工程师，主要使用Java和Python"},
  {"category": "decision", "content": "决定使用Redis作为缓存方案"}
]
```

如果没有值得提取的信息，返回空数组：[]
只输出JSON，不要输出其他内容。"""


class LongTermExtractor:
    """
    长期记忆提取器

    当对话轮次达到阈值（默认10轮）时，从对话中提取关键信息，
    嵌入向量库作为长期记忆。
    """

    def __init__(self, llm: BaseChatModel, store: BaseStore):
        self._llm = llm
        self._store = store

    async def extract_and_store(
        self,
        user_id: str,
        thread_id: str,
        messages: list[dict[str, str]],
    ) -> list[dict[str, Any]]:
        if not messages:
            return []

        extracted = await self._extract(messages)
        if not extracted:
            return []

        stored = []
        namespace = ("users", user_id)

        for idx, item in enumerate(extracted):
            try:
                key = f"{thread_id}_{item.get('category', 'misc')}_{idx}"
                value = {
                    "category": item.get("category", "misc"),
                    "content": item.get("content", ""),
                    "thread_id": thread_id,
                    "source": "auto_extract",
                }
                await self._store.aput(namespace, key, value)
                stored.append(value)
            except Exception as e:
                logger.warning("存储长期记忆失败", key=key, error=str(e))

        logger.info(
            "长期记忆提取完成",
            user_id=user_id,
            thread_id=thread_id,
            extracted=len(extracted),
            stored=len(stored),
        )
        return stored

    async def _extract(
        self, messages: list[dict[str, str]]
    ) -> list[dict[str, Any]]:
        from langchain_core.messages import HumanMessage, SystemMessage

        conversation = self._format_messages(messages)

        response = await self._llm.ainvoke(
            [
                SystemMessage(content=EXTRACT_SYSTEM_PROMPT),
                HumanMessage(
                    content=f"请从以下对话中提取值得长期记住的信息：\n\n{conversation}"
                ),
            ]
        )

        content = response.content
        logger.info(f"提取到的长期记忆：{content}")
        return self._parse_extraction(content)

    @staticmethod
    def _format_messages(messages: list[dict[str, str]]) -> str:
        lines = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if role == "user":
                lines.append(f"用户：{content}")
            elif role == "assistant":
                lines.append(f"助手：{content}")
        return "\n".join(lines)

    @staticmethod
    def _parse_extraction(content: str) -> list[dict[str, Any]]:
        import orjson
        import re

        json_match = re.search(r"\[.*\]", content, re.DOTALL)
        if not json_match:
            return []

        try:
            result = orjson.loads(json_match.group())
            if isinstance(result, list):
                return result
            return []
        except Exception:
            return []


__all__ = ["LongTermExtractor"]
