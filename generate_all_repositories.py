"""
Скрипт для массовой генерации всех репозиториев проекта

Usage:
    python generate_all_repositories.py
"""

from generate_repository import generate_repository


# Список всех моделей для которых нужны репозитории
MODELS = [
    # Organizational structure
    "Organization",
    "OrganizationMember",
    "OrganizationSettings",
    
    "Project",
    "ProjectMember",
    "ProjectSettings",
    
    "Team",
    "TeamMember",
    "TeamSettings",
    
    "User",
    "UserSession",
    
    # VCS data
    "Repository",
    "RepositoryAccess",
    "Commit",
    "CommitFile",
    "Contributor",
    "ContributorAlias",
]


def generate_all():
    """Генерирует репозитории для всех моделей"""
    print("🚀 Генерация репозиториев для всех моделей...\n")
    
    for model_name in MODELS:
        try:
            generate_repository(model_name)
            print()
        except Exception as e:
            print(f"❌ Ошибка при генерации {model_name}: {e}\n")
    
    print("✨ Готово! Проверь директорию src/adapters/db/repositories/")
    print("\n💡 Следующие шаги:")
    print("1. Добавь кастомные методы в каждый репозиторий")
    print("2. Создай __init__.py для удобного импорта")
    print("3. Напиши тесты для репозиториев")


if __name__ == "__main__":
    generate_all()
