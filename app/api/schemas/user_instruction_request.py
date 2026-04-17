from typing import Optional

from pydantic import BaseModel, Field


class UserInstructionRequest(BaseModel):
    user_id: str = Field(..., description="用户ID")
    instruction_content: str = Field(..., description="用户指令内容")


class UserInstructionResponse(BaseModel):
    success: bool = Field(..., description="操作是否成功")
    message: str = Field(..., description="消息")
    version: Optional[int] = Field(default=None, description="版本号")


class UserInstructionGetResponse(BaseModel):
    user_id: str = Field(..., description="用户ID")
    instruction_content: str = Field(..., description="用户指令内容")
    version: int = Field(..., description="版本号")
    updated_at: Optional[str] = Field(default=None, description="更新时间")


class UserInstructionExistsResponse(BaseModel):
    exists: bool = Field(..., description="是否存在自定义指令")
