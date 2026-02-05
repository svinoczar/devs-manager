from sqlalchemy.orm import Session
from sqlalchemy import select
from src.adapters.db.models.file_extension import FileExtensionModel
from src.adapters.db.repositories.base_repository import BaseRepository


class FileExtensionRepository(BaseRepository[FileExtensionModel]):
    def __init__(self, db: Session):
        super().__init__(db, FileExtensionModel)

    def get_language(self, extension: str) -> str | None:
        stmt = select(FileExtensionModel.language).where(
            FileExtensionModel.extension == extension
        )
        return self.db.scalar(stmt)

    def get_by_extension(self, extension: str) -> FileExtensionModel | None:
        stmt = select(FileExtensionModel).where(
            FileExtensionModel.extension == extension
        )
        return self.db.scalar(stmt)

    def get_by_language(self, language: str) -> list[FileExtensionModel]:
        stmt = select(FileExtensionModel).where(
            FileExtensionModel.language == language
        )
        return list(self.db.scalars(stmt).all())

    def add_extension(
        self, 
        extension: str, 
        language: str
    ) -> FileExtensionModel:
        return self.create(extension=extension, language=language)

    def get_or_create(
        self, 
        extension: str, 
        language: str
    ) -> tuple[FileExtensionModel, bool]:
        ext = self.get_by_extension(extension)
        if ext:
            return ext, False

        ext = self.create(extension=extension, language=language)
        return ext, True

    def update_language(
        self, 
        extension: str, 
        new_language: str
    ) -> FileExtensionModel | None:
        ext = self.get_by_extension(extension)
        if not ext:
            return None

        ext.language = new_language
        self.db.commit()
        self.db.refresh(ext)
        return ext

    def get_all_languages(self) -> list[str]:
        stmt = select(FileExtensionModel.language).distinct()
        return list(self.db.scalars(stmt).all())