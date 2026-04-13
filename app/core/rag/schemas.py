from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional



@dataclass
class CodeChunk:
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FileInfo:
    file_path: str
    content: str
    language: str
    size: int = 0


@dataclass
class RepoInfo:
    repo_url: str
    project_name: str
    branch: str
    local_path: str
    file_count: int = 0
    total_size: int = 0


@dataclass
class RetrievalResult:  # 检索结果
    id: str
    project_name: str
    file_path: str
    language: str
    chunk_type: str
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    score: float = 0.0


@dataclass
class Vulnerability:    # 漏洞信息
    vuln_type: str
    severity: str
    file_path: str
    line_range: str
    description: str
    evidence: str
    fix_suggestion: str
    confidence: float = 0.0
    references: List[str] = field(default_factory=list)


@dataclass
class AuditFile:    # 审计文件
    file_path: str
    content: str
    language: Optional[str] = None
    diff: Optional[str] = None


# 语言扩展映射
EXTENSION_LANGUAGE_MAP: Dict[str, str] = {
    ".py": "python",
    ".java": "java",
    ".js": "js",
    ".ts": "ts",
    ".tsx": "ts",
    ".jsx": "js",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".scala": "scala",
    ".kt": "kotlin",
    ".cs": "csharp",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".c": "c",
    ".h": "cpp",
    ".hpp": "cpp",
    ".php": "php",
    ".swift": "swift",
    ".html": "html",
    ".css": "html",
    ".sql": "sql",
    ".sh": "shell",
    ".bash": "shell",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".xml": "xml",
    ".md": "markdown",
    ".vue": "html",
    ".dart": "dart",
}

DEFAULT_TARGET_EXTENSIONS = list(set(EXTENSION_LANGUAGE_MAP.keys()))

# 忽略文件
IGNORE_PATTERNS = [
    ".git/", ".svn/", ".hg/",
    "node_modules/", "__pycache__/", ".venv/", "venv/",
    ".idea/", ".vscode/",
    "dist/", "build/", "target/", "out/",
    ".env", ".DS_Store",
    "*.min.js", "*.min.css",
    "*.lock", "package-lock.json",
    "*.pyc", "*.pyo", "*.class", "*.o", "*.so",
    "*.jar", "*.war", "*.zip", "*.tar.gz",
    "*.png", "*.jpg", "*.jpeg", "*.gif", "*.svg", "*.ico",
    "*.mp3", "*.mp4", "*.wav", "*.avi",
    "*.ttf", "*.woff", "*.woff2", "*.eot",
]


__all__ = [
    "CodeChunk",
    "FileInfo",
    "RepoInfo",
    "RetrievalResult",
    "Vulnerability",
    "AuditFile",
    "EXTENSION_LANGUAGE_MAP",
    "DEFAULT_TARGET_EXTENSIONS",
    "IGNORE_PATTERNS",
]
