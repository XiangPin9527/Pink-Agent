from typing import Optional

from pydantic import BaseModel, Field

from app.core.llm.service import get_llm_service
from app.utils.logger import get_logger

logger = get_logger(__name__)


class QueryList(BaseModel):
    queries: list[str] = Field(description="重构后的查询列表，最多8个")


class AuditQueryRewriter:
    async def rewrite(
        self,
        code_snippet: str,
        language: str = "unknown",
    ) -> list[str]:
        queries = [code_snippet]

        try:
            llm_service = get_llm_service()
            llm = llm_service.get_model()
            structured_llm = llm.with_structured_output(QueryList)

            system_prompt = """你是一个代码安全审计专家。请分析代码片段，生成多个检索查询，用于从代码知识库中检索相关的安全漏洞模式。

生成的查询应包含以下类型：
1. 原始代码片段中的关键模式（如函数调用、API使用方式）
2. 代码功能描述（如"用户认证"、"数据库查询"）
3. 可能存在的安全漏洞类型（如"SQL注入"、"XSS"、"路径遍历"）
4. 代码中使用的关键函数或API名称

请生成3-8个查询，返回JSON格式的字符串数组。"""

            user_prompt = f"""代码片段:
```
{code_snippet[:2000]}
```

编程语言: {language}

请生成检索查询列表："""

            response = await structured_llm.ainvoke([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ])
            if response and isinstance(response, QueryList):
                for q in response.queries:
                    if isinstance(q, str) and q.strip():
                        queries.append(q.strip())
        except Exception as e:
            logger.warning("查询改写失败，使用原始查询", error=str(e))
            key_patterns = self._extract_key_patterns(code_snippet)
            queries.extend(key_patterns)

        return queries[:8]

    @staticmethod
    def _extract_key_patterns(code: str) -> list[str]:
        patterns = []
        import re
        func_calls = re.findall(r'(\w+)\s*\(', code)
        for func in set(func_calls):
            if len(func) > 2 and func not in ("if", "for", "while", "with", "def", "class", "return", "print"):
                patterns.append(func)

        sql_keywords = re.findall(r'\b(SELECT|INSERT|UPDATE|DELETE|FROM|WHERE)\b', code, re.IGNORECASE)
        if sql_keywords:
            patterns.append("SQL query construction")

        file_ops = re.findall(r'\b(open|read|write|file_get_contents|fopen)\s*\(', code)
        if file_ops:
            patterns.append("file operation")

        exec_funcs = re.findall(r'\b(exec|eval|system|subprocess|os\.system|Runtime\.getRuntime)\s*\(', code)
        if exec_funcs:
            patterns.append("command execution")

        return patterns[:5]


_audit_query_rewriter: Optional[AuditQueryRewriter] = None


def get_audit_query_rewriter() -> AuditQueryRewriter:
    global _audit_query_rewriter
    if _audit_query_rewriter is None:
        _audit_query_rewriter = AuditQueryRewriter()
    return _audit_query_rewriter


__all__ = ["AuditQueryRewriter", "get_audit_query_rewriter"]
