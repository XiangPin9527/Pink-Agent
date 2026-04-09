import uuid

from fastapi import APIRouter, Depends

from app.api.schemas.rag_request import RagIngestRequest, RagIngestResponse
from app.config.settings import Settings, get_settings

router = APIRouter()


@router.post("/ingest", response_model=RagIngestResponse)
async def ingest_document(
    request: RagIngestRequest,
    settings: Settings = Depends(get_settings),
):
    """
    文档嵌入接口
    
    将文档内容向量化并存储到向量数据库
    """
    from app.core.rag.engine import RAGEngine

    task_id = str(uuid.uuid4())

    engine = RAGEngine()
    await engine.ingest_document(
        file_url=request.file_url,
        source=request.source,
        tag=request.tag,
    )

    return RagIngestResponse(
        task_id=task_id,
        status="completed",
        message="文档嵌入成功",
    )
