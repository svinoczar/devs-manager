from sqlalchemy.orm import Session
from sqlalchemy import select, delete
from src.adapters.db.models.commit_file import CommitFileModel
from src.adapters.db.repositories.base_repository import BaseRepository


class CommitFileRepository(BaseRepository[CommitFileModel]):
    def __init__(self, db: Session):
        super().__init__(db, CommitFileModel)

    def get_by_commit(self, commit_id: int) -> list[CommitFileModel]:
        stmt = select(CommitFileModel).where(
            CommitFileModel.commit_id == commit_id
        )
        return list(self.db.scalars(stmt).all())

    def get_by_commit_and_path(
        self, 
        commit_id: int, 
        file_path: str
    ) -> CommitFileModel | None:
        stmt = select(CommitFileModel).where(
            CommitFileModel.commit_id == commit_id,
            CommitFileModel.file_path == file_path
        )
        return self.db.scalar(stmt)

    def delete_by_commit_id(self, commit_id: int) -> int:
        stmt = delete(CommitFileModel).where(
            CommitFileModel.commit_id == commit_id
        )
        result = self.db.execute(stmt)
        self.db.commit()
        return result.rowcount

    def bulk_create(self, files: list[CommitFileModel]) -> list[CommitFileModel]:
        self.db.add_all(files)
        self.db.commit()
        
        # Refresh всех объектов чтобы получить их ID
        for file in files:
            self.db.refresh(file)
        
        return files

    def get_or_create(
        self,
        commit_id: int,
        file_path: str,
        **kwargs
    ) -> tuple[CommitFileModel, bool]:
        file = self.get_by_commit_and_path(commit_id, file_path)
        if file:
            return file, False

        file = self.create(
            commit_id=commit_id,
            file_path=file_path,
            **kwargs
        )
        return file, True

    def count_by_commit(self, commit_id: int) -> int:
        stmt = select(CommitFileModel).where(
            CommitFileModel.commit_id == commit_id
        )
        return self.db.query(CommitFileModel).filter(
            CommitFileModel.commit_id == commit_id
        ).count()

    def get_by_language(
        self, 
        commit_id: int, 
        language: str
    ) -> list[CommitFileModel]:
        stmt = select(CommitFileModel).where(
            CommitFileModel.commit_id == commit_id,
            CommitFileModel.language == language
        )
        return list(self.db.scalars(stmt).all())