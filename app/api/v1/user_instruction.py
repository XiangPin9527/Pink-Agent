from fastapi import APIRouter, HTTPException

from app.api.schemas.user_instruction_request import (
    UserInstructionRequest,
    UserInstructionResponse,
    UserInstructionGetResponse,
    UserInstructionExistsResponse,
)
from app.core.memory.user_instruction import get_user_instruction_service
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.post("", response_model=UserInstructionResponse)
async def set_user_instruction(request: UserInstructionRequest):
    """设置用户指令"""
    try:
        service = get_user_instruction_service()
        success = await service.save(request.user_id, request.instruction_content)

        if not success:
            raise HTTPException(status_code=500, detail="保存用户指令失败")

        existing = await service._db.get_user_instruction(request.user_id)
        version = existing.get("version", 1) if existing else 1

        return UserInstructionResponse(
            success=True,
            message="用户指令保存成功",
            version=version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("设置用户指令失败", user_id=request.user_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{user_id}", response_model=UserInstructionGetResponse)
async def get_user_instruction(user_id: str):
    """获取用户指令"""
    try:
        service = get_user_instruction_service()
        content = await service.get(user_id)

        if not content:
            raise HTTPException(status_code=404, detail="用户指令不存在")

        db_data = await service._db.get_user_instruction(user_id)
        version = db_data.get("version", 1) if db_data else 1
        updated_at = db_data.get("updated_at") if db_data else None

        return UserInstructionGetResponse(
            user_id=user_id,
            instruction_content=content,
            version=version,
            updated_at=updated_at,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("获取用户指令失败", user_id=user_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{user_id}", response_model=UserInstructionResponse)
async def delete_user_instruction(user_id: str):
    """删除用户指令"""
    try:
        service = get_user_instruction_service()
        success = await service.delete(user_id)

        if not success:
            raise HTTPException(status_code=500, detail="删除用户指令失败")

        return UserInstructionResponse(
            success=True,
            message="用户指令已删除",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("删除用户指令失败", user_id=user_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{user_id}/exists", response_model=UserInstructionExistsResponse)
async def check_user_instruction_exists(user_id: str):
    """检查用户是否有自定义指令"""
    try:
        service = get_user_instruction_service()
        exists = await service.exists(user_id)

        return UserInstructionExistsResponse(exists=exists)
    except Exception as e:
        logger.error("检查用户指令存在性失败", user_id=user_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
