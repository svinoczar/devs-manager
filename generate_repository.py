"""
Скрипт для быстрой генерации репозиториев

Usage:
    python generate_repository.py ModelName

Example:
    python generate_repository.py User
    # Создаст src/adapters/db/repositories/user_repo.py
"""

import sys
import os
from pathlib import Path


TEMPLATE = """from sqlalchemy.orm import Session
from sqlalchemy import select
from src.adapters.db.models.{model_file} import {model_class}
from src.adapters.db.repositories.base_repository import BaseRepository


class {repo_class}(BaseRepository[{model_class}]):
    def __init__(self, db: Session):
        super().__init__(db, {model_class})

    # Добавь здесь кастомные методы для {model_class}
    
    # Примеры:
    # def get_by_name(self, name: str) -> {model_class} | None:
    #     stmt = select({model_class}).where({model_class}.name == name)
    #     return self.db.scalar(stmt)
    
    # def get_or_create(self, **kwargs) -> tuple[{model_class}, bool]:
    #     instance = self.get_by_id(kwargs.get('id'))
    #     if instance:
    #         return instance, False
    #     return self.create(**kwargs), True
"""


def to_snake_case(name: str) -> str:
    """Convert CamelCase to snake_case"""
    import re
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()


def generate_repository(model_name: str, output_dir: str = "src/adapters/db/repositories"):
    """
    Генерирует базовый репозиторий для модели
    
    Args:
        model_name: Имя модели (например: User, Organization)
        output_dir: Директория для сохранения
    """
    # Убираем 'Model' если есть
    if model_name.endswith('Model'):
        model_name = model_name[:-5]
    
    model_class = f"{model_name}Model"
    repo_class = f"{model_name}Repository"
    model_file = to_snake_case(model_name)
    repo_file = f"{model_file}_repo.py"
    
    # Создаем контент
    content = TEMPLATE.format(
        model_class=model_class,
        repo_class=repo_class,
        model_file=model_file
    )
    
    # Создаем директорию если не существует
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    # Записываем файл
    output_path = os.path.join(output_dir, repo_file)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"✅ Создан репозиторий: {output_path}")
    print(f"   Класс: {repo_class}")
    print(f"   Модель: {model_class}")
    print(f"\nТеперь добавь кастомные методы в класс!")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python generate_repository.py ModelName")
        print("\nExamples:")
        print("  python generate_repository.py User")
        print("  python generate_repository.py OrganizationSettings")
        print("  python generate_repository.py TeamMember")
        sys.exit(1)
    
    model_name = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "src/adapters/db/repositories"
    
    generate_repository(model_name, output_dir)
