import os
import asyncio
import tempfile
import fnmatch
from typing import Optional

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
        temp_dir = tempfile.mkdtemp(prefix="rag_repo_")
        cmd = ["git", "clone", "--branch", branch]
        if shallow:
            cmd.extend(["--depth", "1"])
        cmd.extend([repo_url, temp_dir])

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode("utf-8", errors="replace").strip()
            logger.error("Git 克隆失败", repo_url=repo_url, error=error_msg)
            raise RuntimeError(f"Git clone failed: {error_msg}")

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
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
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
            await asyncio.get_event_loop().run_in_executor(
                None, shutil.rmtree, local_path
            )
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
