from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.infrastructure.redis_client import get_redis
from app.utils.logger import get_logger

logger = get_logger(__name__)

SUMMARY_TTL_SECONDS = 3600
MIN_MESSAGES_FOR_SUMMARY = 10
RECENT_ROUNDS_TO_KEEP = 5

SUMMARY_SYSTEM_PROMPT = """# ROLE
你是一个专业的信息萃取专家。你的任务是将一段原始的对话历史转化成一份高度精炼、结构化的「核心上下文快照」。

# GOAL
通过去除冗余和提取关键事实，确保后续 AI 仅通过阅读此快照就能完美掌握该阶段的进展。

# EXTRACTION RULES (萃取准则)
1. 绝对去噪：剔除所有“你好”、“谢谢”、“明白了”、“正在为你查询”等废话，以及所有的纠错迭代过程，只保留最终确定的正确结果。
2. 实体捕捉：重点识别并保留人名、项目名、技术栈（如 Redis, Python）、特定参数或数值。
3. 状态识别：区分哪些事是「已定论」的，哪些事是「正在做」或「用户要求的」。
4. 结构化呈现：使用主题分类，不要写流水账。

# OUTPUT FORMAT
请严格按照以下 Markdown 结构输出，如果没有相关内容则不显示该子项（但保留大标题）：

## 👤 用户画像与偏好 (User Context)
- (如：用户是西安电子科技大学研二学生；偏好 Java 后端开发；正在准备实习面试)

## 📌 关键决议与事实 (Key Facts)
- [主题名称]：描述最终确定的事实或结论（如：[缓存架构] 确定采用 Redis + PostgreSQL 两级架构）。

## ⏳ 遗留问题与当前任务 (Open Loops)
- (描述本段对话结束时，用户正在处理的事或 AI 需要在下一阶段响应的请求)

## 🛠️ 涉及技术/名词 (Tech Stack)
- (列出本段对话提到的关键工具、库、协议或专业术语)

---
..."""


class SummaryService:
    """
    智能摘要服务

    策略：
    - 当消息列表 ≥ MIN_MESSAGES_FOR_SUMMARY 条时，生成前 N-5 轮的摘要
    - 摘要存储在 Redis，TTL 30 分钟
    - 异步生成，不影响用户对话延迟
    """

    def __init__(self, llm: BaseChatModel):
        self._llm = llm

    async def generate_and_store(
        self, thread_id: str, messages: list[dict[str, str]]
    ) -> str | None:
        if len(messages) < MIN_MESSAGES_FOR_SUMMARY:
            logger.debug(
                "消息数不足，跳过摘要生成",
                thread_id=thread_id,
                count=len(messages),
                min_required=MIN_MESSAGES_FOR_SUMMARY,
            )
            return None

        recent_count = RECENT_ROUNDS_TO_KEEP * 2
        older_messages = messages[:-recent_count] if len(messages) > recent_count else messages

        if not older_messages:
            return None

        summary = await self._generate_summary(older_messages)

        if summary:
            await self._store_summary(thread_id, summary)

        return summary

    async def get_summary(self, thread_id: str) -> str | None:
        try:
            r = await get_redis()
            key = f"summary:{thread_id}"
            summary = await r.get(key)
            if summary:
                logger.debug("从 Redis 获取摘要", thread_id=thread_id)
            return summary
        except Exception as e:
            logger.warning("获取摘要失败", thread_id=thread_id, error=str(e))
            return None

    async def _generate_summary(self, messages: list[dict[str, str]]) -> str | None:
        conversation_text = self._format_messages(messages)

        try:
            response = await self._llm.ainvoke(
                [
                    SystemMessage(content=SUMMARY_SYSTEM_PROMPT),
                    HumanMessage(
                        content=f"请对以下对话历史进行摘要提炼：\n\n{conversation_text}"
                    ),
                ]
            )
            summary = response.content
            logger.info("摘要生成成功", input_msgs=len(messages), summary_len=len(summary))
            return summary
        except Exception as e:
            logger.error("摘要生成失败", error=str(e))
            return None

    async def _store_summary(self, thread_id: str, summary: str) -> None:
        try:
            r = await get_redis()
            key = f"summary:{thread_id}"
            await r.set(key, summary, ex=SUMMARY_TTL_SECONDS)
            logger.debug("摘要已存储到 Redis", thread_id=thread_id, ttl=SUMMARY_TTL_SECONDS)
        except Exception as e:
            logger.warning("存储摘要失败", thread_id=thread_id, error=str(e))

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
            else:
                lines.append(f"{role}：{content}")
        return "\n".join(lines)


__all__ = ["SummaryService"]
