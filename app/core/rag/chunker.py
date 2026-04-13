import hashlib
from typing import Optional

from langchain_text_splitters import Language, RecursiveCharacterTextSplitter

from app.core.rag.schemas import CodeChunk, EXTENSION_LANGUAGE_MAP
from app.utils.logger import get_logger

logger = get_logger(__name__)

_LANGCHAIN_LANG_MAP = {
    "python": Language.PYTHON,
    "java": Language.JAVA,
    "js": Language.JS,
    "ts": Language.TS,
    "go": Language.GO,
    "rust": Language.RUST,
    "ruby": Language.RUBY,
    "scala": Language.SCALA,
    "kotlin": Language.KOTLIN,
    "csharp": Language.CSHARP,
    "cpp": Language.CPP,
    "c": Language.C,
    "php": Language.PHP,
    "swift": Language.SWIFT,
    "html": Language.HTML,
    "markdown": Language.MARKDOWN,
    "latex": Language.LATEX,
    "sol": Language.SOL,
    "cobol": Language.COBOL,
    "lua": Language.LUA,
    "perl": Language.PERL,
    "haskell": Language.HASKELL,
    "elixir": Language.ELIXIR,
    "powershell": Language.POWERSHELL,
    "visualbasic6": Language.VISUALBASIC6,
    "proto": Language.PROTO,
    "rst": Language.RST,
}


class CodeChunker:
    CHUNK_SIZE = 1500
    CHUNK_OVERLAP = 200

    # 文件分块
    def chunk_file(
        self,
        file_path: str,
        content: str,
        project_name: str,
        language: Optional[str] = None,
    ) -> list[CodeChunk]:
        if not content or not content.strip():
            return []

        if language is None:
            language = self._detect_language(file_path)

        langchain_lang = _LANGCHAIN_LANG_MAP.get(language) if language else None

        if langchain_lang is not None:
            chunks = self._split_with_language(content, langchain_lang)
        else:
            chunks = self._fallback_split(content)

        result = []
        for chunk_content in chunks:
            enhanced = self._add_context_header(chunk_content, file_path, language)
            content_hash = hashlib.md5(enhanced.encode("utf-8")).hexdigest()
            result.append(CodeChunk(
                content=enhanced,
                metadata={
                    "project_name": project_name,
                    "file_path": file_path,
                    "language": language or "unknown",
                    "chunk_type": self._detect_chunk_type(chunk_content),
                    "content_hash": content_hash,
                },
            ))

        return result

    def _split_with_language(
        self, content: str, language: Language
    ) -> list[str]:
        try:
            splitter = RecursiveCharacterTextSplitter.from_language(
                language=language,
                chunk_size=self.CHUNK_SIZE,
                chunk_overlap=self.CHUNK_OVERLAP,
            )
            docs = splitter.create_documents([content])
            return [doc.page_content for doc in docs]
        except Exception as e:
            logger.warning("语言切块失败，降级为通用切块", language=language, error=str(e))
            return self._fallback_split(content)

    def _fallback_split(self, content: str) -> list[str]:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.CHUNK_SIZE,
            chunk_overlap=self.CHUNK_OVERLAP,
            separators=["\n\n", "\n", " ", ""],
        )
        docs = splitter.create_documents([content])
        return [doc.page_content for doc in docs]

    @staticmethod
    def _add_context_header(
        content: str, file_path: str, language: Optional[str]
    ) -> str:
        header = f"# File: {file_path}\n"
        if language:
            header += f"# Language: {language}\n"
        header += "# ---\n"
        return header + content

    @staticmethod
    def _detect_language(file_path: str) -> Optional[str]:
        import os
        _, ext = os.path.splitext(file_path.lower())
        return EXTENSION_LANGUAGE_MAP.get(ext)

    @staticmethod
    def _detect_chunk_type(content: str) -> str:
        content_lower = content.lower()
        if "class " in content_lower:
            return "class"
        if "def " in content_lower or "function " in content_lower or "func " in content_lower:
            return "function"
        if "import " in content_lower or "from " in content_lower or "require(" in content_lower:
            return "import"
        return "code"


_code_chunker: Optional[CodeChunker] = None


def get_code_chunker() -> CodeChunker:
    global _code_chunker
    if _code_chunker is None:
        _code_chunker = CodeChunker()
    return _code_chunker


__all__ = ["CodeChunker", "get_code_chunker"]
