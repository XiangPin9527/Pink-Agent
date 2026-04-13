from typing import Optional

from pydantic import BaseModel, Field


class AuditFileModel(BaseModel):
    file_path: str = Field(..., description="文件路径")
    content: str = Field(..., description="文件内容")
    language: Optional[str] = Field(default=None, description="编程语言")
    diff: Optional[str] = Field(default=None, description="代码变更 diff")


class AuditRequest(BaseModel):
    user_id: str = Field(..., description="用户 ID")
    session_id: str = Field(..., description="会话 ID")
    project_name: str = Field(..., description="项目名称（用于限定检索范围）")
    files: list[AuditFileModel] = Field(..., description="待审计文件列表")
    audit_type: str = Field(
        default="security",
        description="审计类型: security(安全审计)/quality(代码质量)/compliance(合规检查)",
    )


class AuditStreamRequest(BaseModel):
    user_id: str = Field(..., description="用户 ID")
    session_id: str = Field(..., description="会话 ID")
    project_name: str = Field(..., description="项目名称")
    files: list[AuditFileModel] = Field(..., description="待审计文件列表")
    audit_type: str = Field(default="security", description="审计类型")


class AuditResponse(BaseModel):
    trace_id: str
    session_id: str
    user_id: str
    content: str
    is_completed: bool
    vuln_count: int = 0
    vulnerabilities: list[dict] = Field(default_factory=list)
