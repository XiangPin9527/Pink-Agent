import os
import asyncio
import fnmatch
import uuid
from typing import Optional

import git

from app.core.rag.schemas import FileInfo, RepoInfo, IGNORE_PATTERNS, DEFAULT_TARGET_EXTENSIONS
from app.utils.logger import get_logger

logger = get_logger(__name__)


class GitRepoLoader:
    async def clone_repo(
        self,
        repo_url: str,
        branch: str = "main",
        project_name: str = "",
        shallow: bool = True,
        target_extensions: Optional[list[str]] = None,
    ) -> RepoInfo:
        logger.info("开始克隆仓库", repo_url=repo_url, branch=branch)

        sub_dir = f"rag_repo_{uuid.uuid4().hex[:8]}"
        temp_dir = os.path.join(r"E:\Python\Temp", sub_dir)
        os.makedirs(temp_dir, exist_ok=True)

        def _do_clone():
            return git.Repo.clone_from(
                url=repo_url,
                to_path=temp_dir,
                branch=branch,
                depth=1 if shallow else None,
                env={"GIT_TERMINAL_PROMPT": "0"},
                allow_unsafe_protocols=True,
                allow_unsafe_options=True,
            )

        try:
            repo = await asyncio.to_thread(_do_clone)
            await asyncio.to_thread(repo.close)
            del repo
        except git.GitCommandError as e:
            logger.error("Git 克隆失败", repo_url=repo_url, error=str(e))
            raise RuntimeError(f"Git clone failed: {e.stderr}") from e
        except Exception as e:
            logger.error("Git 克隆失败", repo_url=repo_url, error=str(e))
            raise RuntimeError(f"Git clone failed: {e}") from e

        logger.info("Git 仓库克隆完成", repo_url=repo_url, local_path=temp_dir)

        return RepoInfo(
            repo_url=repo_url,
            project_name=project_name,
            branch=branch,
            local_path=temp_dir,
            file_count=0,
            total_size=0,
        )

    async def scan_files_async(
        self,
        repo_path: str,
        target_extensions: Optional[list[str]] = None,
        ignore_patterns: Optional[list[str]] = None,
    ) -> list[FileInfo]:
        return await asyncio.to_thread(
            self.scan_files,
            repo_path,
            target_extensions,
            ignore_patterns,
        )

    def scan_files(
        self,
        repo_path: str,
        target_extensions: Optional[list[str]] = None,
        ignore_patterns: Optional[list[str]] = None,
    ) -> list[FileInfo]:
        extensions = set(target_extensions or DEFAULT_TARGET_EXTENSIONS)
        ignores = ignore_patterns or IGNORE_PATTERNS
        files = []

        for root, dirs, filenames in os.walk(repo_path):
            rel_root = os.path.relpath(root, repo_path)
            rel_root = rel_root.replace("\\", "/")

            dirs_to_remove = []
            for d in dirs:
                dir_rel = os.path.join(rel_root, d).replace("\\", "/") + "/"
                if self._should_ignore(dir_rel, ignores):
                    dirs_to_remove.append(d)
            for d in dirs_to_remove:
                dirs.remove(d)

            for filename in filenames:
                _, ext = os.path.splitext(filename.lower())
                if ext not in extensions:
                    continue

                file_rel = os.path.join(rel_root, filename).replace("\\", "/")
                if self._should_ignore(file_rel, ignores):
                    continue

                full_path = os.path.join(root, filename)
                try:
                    with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                except Exception as e:
                    logger.warning("读取文件失败，跳过", file_path=file_rel, error=str(e))
                    continue

                language = self._detect_language(ext)
                file_size = os.path.getsize(full_path)

                files.append(FileInfo(
                    file_path=file_rel,
                    content=content,
                    language=language,
                    size=file_size,
                ))

        logger.info("仓库文件扫描完成", repo_path=repo_path, file_count=len(files))
        return files

    @staticmethod
    def _should_ignore(path: str, patterns: list[str]) -> bool:
        for pattern in patterns:
            if pattern.endswith("/"):
                if pattern.rstrip("/") in path:
                    return True
            elif pattern.startswith("*"):
                if fnmatch.fnmatch(path, pattern):
                    return True
            elif pattern in path:
                return True
        return False

    @staticmethod
    def _detect_language(ext: str) -> str:
        from app.core.rag.schemas import EXTENSION_LANGUAGE_MAP
        return EXTENSION_LANGUAGE_MAP.get(ext, "unknown")

    @staticmethod
    async def cleanup(local_path: str):
        import shutil
        try:
            await asyncio.to_thread(shutil.rmtree, local_path)
            logger.debug("临时目录已清理", local_path=local_path)
        except Exception as e:
            logger.warning("清理临时目录失败", local_path=local_path, error=str(e))


_git_repo_loader: Optional[GitRepoLoader] = None


def get_git_repo_loader() -> GitRepoLoader:
    global _git_repo_loader
    if _git_repo_loader is None:
        _git_repo_loader = GitRepoLoader()
    return _git_repo_loader


__all__ = ["GitRepoLoader", "get_git_repo_loader"]
