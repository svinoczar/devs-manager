import asyncio
import json
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from src.api.dependencies import get_db, get_current_user
from src.adapters.db.models.user import UserModel
from src.adapters.db.repositories.sync_session_repo import SyncSessionRepository
from src.adapters.db.models.sync_session import SyncStatus
from src.util.logger import logger

router = APIRouter(prefix="/sync", tags=["sync"])


async def progress_stream(
    session_id: int,
    db: Session
) -> AsyncGenerator[str, None]:
    """
    SSE поток прогресса синхронизации.
    Отправляет обновления каждые 500ms до завершения синхронизации.

    Args:
        session_id: ID сессии синхронизации
        db: Database session

    Yields:
        SSE события в формате "data: {...}\n\n"
    """
    sync_repo = SyncSessionRepository(db)

    last_status = None
    retry_count = 0
    max_retries = 240  # 120 seconds max (240 * 0.5s)

    while retry_count < max_retries:
        sync_session = sync_repo.get_by_id(session_id)

        if not sync_session:
            yield f"event: error\ndata: {json.dumps({'error': 'Session not found'})}\n\n"
            break

        # Формируем данные прогресса
        progress_data = {
            "session_id": session_id,
            "status": sync_session.status.value,
            "total_commits": sync_session.total_commits,
            "processed_commits": sync_session.processed_commits,
            "new_commits": sync_session.new_commits,
            "progress_percent": (
                int((sync_session.processed_commits / sync_session.total_commits) * 100)
                if sync_session.total_commits > 0 else 0
            ),
            "current_phase": sync_session.current_phase,
            "sprint_commits_done": sync_session.sprint_commits_done,
            "errors": sync_session.errors.get("errors", []) if sync_session.errors else [],
        }

        # Отправляем только если изменилось
        if progress_data != last_status:
            yield f"data: {json.dumps(progress_data)}\n\n"
            last_status = progress_data

        # Завершаем при финальном статусе
        if sync_session.status in [SyncStatus.completed, SyncStatus.failed, SyncStatus.cancelled]:
            yield f"event: complete\ndata: {json.dumps(progress_data)}\n\n"
            logger.info("SSE stream completed for session %d", session_id)
            break

        # Heartbeat каждые 30 секунд (60 итераций * 0.5s)
        if retry_count % 60 == 0 and retry_count > 0:
            yield ": heartbeat\n\n"

        retry_count += 1
        await asyncio.sleep(0.5)

    # Если превышен timeout
    if retry_count >= max_retries:
        yield f"event: timeout\ndata: {json.dumps({'error': 'Stream timeout'})}\n\n"
        logger.warning("SSE stream timeout for session %d", session_id)


@router.get("/progress/{session_id}")
async def get_sync_progress(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    """
    SSE endpoint для получения прогресса синхронизации в реальном времени.

    Args:
        session_id: ID сессии синхронизации
        db: Database session
        current_user: Текущий пользователь (для авторизации)

    Returns:
        StreamingResponse с SSE событиями

    Example (frontend):
        ```javascript
        const eventSource = new EventSource('/sync/progress/123');
        eventSource.onmessage = (e) => {
            const data = JSON.parse(e.data);
            console.log('Progress:', data.progress_percent, '%');
        };
        eventSource.addEventListener('complete', (e) => {
            const data = JSON.parse(e.data);
            console.log('Sync completed!', data);
            eventSource.close();
        });
        ```
    """
    # Проверяем существование сессии
    sync_repo = SyncSessionRepository(db)
    sync_session = sync_repo.get_by_id(session_id)

    if not sync_session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sync session {session_id} not found"
        )

    logger.info("Starting SSE stream for session %d (user: %s)", session_id, current_user.username)

    return StreamingResponse(
        progress_stream(session_id, db),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Для nginx
        }
    )


@router.get("/status/{session_id}")
def get_sync_status(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    """
    Получить текущий статус сессии синхронизации (polling fallback для SSE).

    Args:
        session_id: ID сессии синхронизации
        db: Database session
        current_user: Текущий пользователь (для авторизации)

    Returns:
        Текущий прогресс синхронизации
    """
    sync_repo = SyncSessionRepository(db)
    sync_session = sync_repo.get_by_id(session_id)

    if not sync_session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sync session {session_id} not found"
        )

    return {
        "session_id": session_id,
        "status": sync_session.status.value,
        "total_commits": sync_session.total_commits,
        "processed_commits": sync_session.processed_commits,
        "new_commits": sync_session.new_commits,
        "progress_percent": (
            int((sync_session.processed_commits / sync_session.total_commits) * 100)
            if sync_session.total_commits and sync_session.total_commits > 0 else 0
        ),
        "current_phase": sync_session.current_phase,
        "sprint_commits_done": sync_session.sprint_commits_done,
        "errors": sync_session.errors.get("errors", []) if sync_session.errors else [],
    }
