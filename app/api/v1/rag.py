import uuid

from fastapi import APIRouter, HTTPException

from app.api.schemas.rag_request import (
    RepoIngestRequest,
    FileIngestRequest,
    RagIngestResponse,
    RagTaskStatusResponse,
    ProjectInfoResponse,
    ProjectStatusResponse,
    DeleteProjectResponse,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.post("/ingest/repo", response_model=RagIngestResponse)
async def ingest_repo(request: RepoIngestRequest):
    task_id = str(uuid.uuid4())

    try:
        from app.infrastructure.mq_publisher import get_mq_publisher
        publisher = get_mq_publisher()
        ok = await publisher.publish_rag_ingest_repo(
            task_id=task_id,
            repo_url=request.repo_url,
            project_name=request.project_name,
            branch=request.branch,
            target_extensions=request.target_extensions,
        )
        logger.info("提交仓库入库任务成功", task_id=task_id)

        if not ok:
            raise HTTPException(status_code=500, detail="消息发布失败")

        return RagIngestResponse(
            task_id=task_id,
            status="processing",
            message="仓库入库任务已提交",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("提交仓库入库任务失败", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ingest/files", response_model=RagIngestResponse)
async def ingest_files(request: FileIngestRequest):
    task_id = str(uuid.uuid4())

    try:
        from app.infrastructure.mq_publisher import get_mq_publisher
        publisher = get_mq_publisher()
        ok = await publisher.publish_rag_ingest_files(
            task_id=task_id,
            project_name=request.project_name,
            files=request.files,
        )

        if not ok:
            raise HTTPException(status_code=500, detail="消息发布失败")

        return RagIngestResponse(
            task_id=task_id,
            status="processing",
            message="文件入库任务已提交",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("提交文件入库任务失败", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks/{task_id}", response_model=RagTaskStatusResponse)
async def get_task_status(task_id: str):
    try:
        from app.infrastructure.redis_service import get_redis_service
        redis_service = get_redis_service()
        status = await redis_service.get_rag_task_status(task_id)

        if status is None:
            raise HTTPException(status_code=404, detail="任务不存在")

        return RagTaskStatusResponse(
            task_id=task_id,
            status=status.get("status", "unknown"),
            result=status.get("result"),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("查询任务状态失败", task_id=task_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects", response_model=list[ProjectInfoResponse])
async def list_projects():
    try:
        from app.core.rag.engine import get_rag_engine
        rag_engine = get_rag_engine()
        projects = await rag_engine.list_projects()
        return [
            ProjectInfoResponse(
                project_name=p.get("project_name", ""),
                chunk_count=p.get("chunk_count", 0),
                file_count=p.get("file_count", 0),
            )
            for p in projects
        ]
    except Exception as e:
        logger.error("列出项目失败", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/{project_name}", response_model=ProjectStatusResponse)
async def get_project_status(project_name: str):
    try:
        from app.core.rag.engine import get_rag_engine
        rag_engine = get_rag_engine()
        status = await rag_engine.get_project_status(project_name)

        if status is None:
            raise HTTPException(status_code=404, detail="项目不存在")

        return ProjectStatusResponse(
            project_name=status.get("project_name", ""),
            chunk_count=status.get("chunk_count", 0),
            file_count=status.get("file_count", 0),
            language_count=status.get("language_count", 0),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("查询项目状态失败", project_name=project_name, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/projects/{project_name}", response_model=DeleteProjectResponse)
async def delete_project(project_name: str):
    try:
        from app.core.rag.engine import get_rag_engine
        rag_engine = get_rag_engine()
        count = await rag_engine.delete_project(project_name)
        return DeleteProjectResponse(project_name=project_name, deleted_count=count)
    except Exception as e:
        logger.error("删除项目失败", project_name=project_name, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
