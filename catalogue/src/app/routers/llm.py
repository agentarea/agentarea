import uuid
from fastapi import APIRouter, HTTPException, Depends, Path, Query
from typing import List, Optional

from ..schemas.llm import (
    ConnectionStatus,
    CreateLLMReferenceRequest,
    LLMInstance,
    CreateLLMInstance,
    LLMReference,
    LLMScope,
)


from ..services.llm_service import LLMService
from ..models.llm import LLMInstance as DBLLMInstance, LLMReference as DBLLMReference
from .dependencies import get_llm_service

# Изменяем префикс, убирая /llm, так как он будет добавлен в основном роутере
router = APIRouter(tags=["llm"])


@router.get(
    "/",
    response_model=List[LLMInstance],
    summary="Получить список LLM",
    description="Возвращает список всех доступных LLM в системе",
)
async def get_llm_instances(
    # inject service
    llm_service: LLMService = Depends(get_llm_service),
):
    """
    Получить список всех доступных типов LLM в системе
    """
    # TODO: Implement catalog retrieval from database
    return await llm_service.get_instances()


@router.post(
    "/",
    response_model=LLMInstance,
    summary="Добавить новую LLM",
    description="Добавляет новую LLM в систему",
)
async def add_llm_instance(
    llm: CreateLLMInstance,
    llm_service: LLMService = Depends(get_llm_service),
):
    """
    Добавить новую LLM в систему
    """

    return await llm_service.add_instance(DBLLMInstance(**llm.model_dump()))


@router.get(
    "/references",
    response_model=List[LLMReference],
    summary="Получить список референсов",
    description="Возвращает список всех референсов с возможностью фильтрации по типу и области видимости",
)
async def get_llm_references(
    scope: Optional[LLMScope] = Query(None, description="Фильтр по области видимости"),
    llm_service: LLMService = Depends(get_llm_service),
):
    """
    Получить список всех настроенных экземпляров LLM с возможностью фильтрации
    """
    # TODO: Implement instances retrieval with filtering
    return await llm_service.get_references(scope)


@router.post(
    "/references",
    response_model=LLMReference,
    summary="Создать новый референс",
    description="Создает новый референс на основе существующего инстанса LLM",
)
async def create_llm_reference(
    reference_data: CreateLLMReferenceRequest,
    llm_service: LLMService = Depends(get_llm_service),
):
    """
    Создать новый экземпляр LLM на основе каталога с указанными настройками
    """
    reference = await llm_service.create_reference(
        instance_id=reference_data.instance_id,
        name=reference_data.name,
        settings=reference_data.settings.model_dump(),
        scope=reference_data.scope,
    )
    return reference


@router.get(
    "/references/{reference_id}",
    response_model=LLMReference,
    summary="Получить референс",
    description="Возвращает информацию о конкретном референсе по его ID",
)
async def get_llm_reference(
    reference_id: str = Path(..., description="ID референса для получения"),
    llm_service: LLMService = Depends(get_llm_service),
):
    """
    Получить информацию о конкретном экземпляре LLM
    """
    reference = await llm_service.get_reference(reference_id)
    return reference


@router.delete(
    "/references/{reference_id}",
    summary="Удалить референс",
    description="Удаляет указанный референс из системы",
)
async def delete_llm_reference(
    reference_id: str = Path(..., description="ID референса для удаления"),
    llm_service: LLMService = Depends(get_llm_service),
):
    """
    Удалить экземпляр LLM
    """
    return await llm_service.delete_reference(reference_id)


@router.post(
    "/references/{reference_id}/check-connection",
    response_model=ConnectionStatus,
    summary="Проверить соединение",
    description="Проверяет соединение с LLM и возвращает статус подключения",
)
async def check_llm_connection(
    reference_id: str = Path(..., description="ID референса для проверки"),
    llm_service: LLMService = Depends(get_llm_service),
):
    """
    Проверить соединение с LLM и её работоспособность.
    Возвращает статус соединения, сообщение, задержку и дополнительную информацию.
    """
    return await llm_service.check_connection(reference_id)
    # TODO: Implement connection check logic:
    # 1. Get LLM instance by id
    # 2. Try to connect based on type (API/LOCAL)
    # 3. Measure latency
    # 4. Run simple test prompt
    # 5. Return connection status
    pass
