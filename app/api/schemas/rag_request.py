from typing import Optional

from pydantic import BaseModel, Field


class RagIngestRequest(BaseModel):
    file_url: str = Field(..., description="文件URL")
    source: str = Field(default="", description="来源标识")
    tag: str = Field(default="", description="标签")


class RagIngestResponse(BaseModel):
    task_id: str = Field(..., description="任务ID")
    status: str = Field(default="processing", description="状态")
    message: Optional[str] = Field(default=None, description="消息")
