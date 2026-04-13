from typing import Optional

from pydantic import BaseModel, Field


class RepoIngestRequest(BaseModel):
    repo_url: str = Field(..., description="Git 仓库 URL")
    branch: str = Field(default="main", description="分支名")
    project_name: str = Field(..., description="项目名称（元数据标识）")
    target_extensions: Optional[list[str]] = Field(
        default=None,
        description="目标文件扩展名，如 ['.py', '.java']",
    )


class FileIngestRequest(BaseModel):
    project_name: str = Field(..., description="项目名称")
    files: list[dict[str, str]] = Field(
        ...,
        description="文件列表，每个元素包含 file_path, content, language(可选)",
    )


class RagIngestResponse(BaseModel):
    task_id: str = Field(..., description="异步任务 ID")
    status: str = Field(default="processing", description="状态")
    message: Optional[str] = Field(default=None, description="消息")


class RagTaskStatusResponse(BaseModel):
    task_id: str = Field(..., description="任务 ID")
    status: str = Field(..., description="状态: processing/completed/failed")
    result: Optional[dict] = Field(default=None, description="结果详情")


class ProjectInfoResponse(BaseModel):
    project_name: str
    chunk_count: int
    file_count: int


class ProjectStatusResponse(BaseModel):
    project_name: str
    chunk_count: int
    file_count: int
    language_count: int


class DeleteProjectResponse(BaseModel):
    project_name: str
    deleted_count: int
