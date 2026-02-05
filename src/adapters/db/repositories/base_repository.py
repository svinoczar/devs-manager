from typing import Generic, TypeVar, Type, List
from sqlalchemy.orm import Session
from sqlalchemy import select

ModelType = TypeVar("ModelType")


class BaseRepository(Generic[ModelType]):
    def __init__(self, db: Session, model: Type[ModelType]):
        self.db = db
        self.model = model

    def create(self, **kwargs) -> ModelType:
        instance = self.model(**kwargs)
        self.db.add(instance)
        self.db.commit()
        self.db.refresh(instance)
        return instance

    def get_by_id(self, id: int) -> ModelType | None:
        return self.db.get(self.model, id)

    def get_all(self, limit: int = 100, offset: int = 0) -> List[ModelType]:
        stmt = select(self.model).limit(limit).offset(offset)
        return list(self.db.scalars(stmt).all())

    def update(self, id: int, **kwargs) -> ModelType | None:
        instance = self.get_by_id(id)
        if not instance:
            return None
        
        for key, value in kwargs.items():
            if hasattr(instance, key):
                setattr(instance, key, value)
        
        self.db.commit()
        self.db.refresh(instance)
        return instance

    def delete(self, id: int) -> bool:
        instance = self.get_by_id(id)
        if not instance:
            return False
        
        self.db.delete(instance)
        self.db.commit()
        return True

    def count(self) -> int:
        return self.db.query(self.model).count()

    def exists(self, id: int) -> bool:
        return self.get_by_id(id) is not None
