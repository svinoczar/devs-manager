from typing import Optional

from src.adapters.db.base import SessionLocal
from src.data.github_api_response.commits_response_entity import SingleCommitEntity
from src.data.domain.commit import Commit
from src.services.internal.preprocessing.file_language_enricher import (
    FileLanguageEnricher,
)
from src.services.internal.preprocessing.commit_type_detector import (
    HeuristicCommitClassifier,
)

import json


class CommitEnricher:
    def __init__(
        self,
        file_enricher: FileLanguageEnricher,
        commit_type_detector: HeuristicCommitClassifier,
    ):
        self.file_enricher = file_enricher
        self.commit_type_detector = commit_type_detector

    def enrich(
        self,
        commit_model: Commit,
        commit_entity: SingleCommitEntity,
        scope_type,
        scope_id,
        session: SessionLocal,
    ) -> Commit:
        team_repo = TeamRepository(session)

        settings = (
            team_repo
                .get_settings(scope_type, scope_id)
                .settings
        )

        if not commit_model.files:
            commit_model.commit_type = "unknown"
            return commit_model

        for file in commit_model.files:
            self.file_enricher.enrich(file)

        commit_meta_data = self.commit_type_detector.detect(commit_entity, settings)

        commit_model.commit_type = commit_meta_data.get("commit_type", "unknown")
        commit_model.is_conventional = commit_meta_data.get("is_conventional", False)
        commit_model.conventional_type = commit_meta_data.get("conventional_type", "unknown")
        commit_model.conventional_scope = commit_meta_data.get("conventional_scope", "unknown")
        commit_model.is_breaking_change = commit_meta_data.get("is_breaking_change", False)
        commit_model.parents_count = commit_meta_data.get("parents_count", 0)
        commit_model.is_merge_commit = commit_meta_data.get("is_merge_commit", False)
        commit_model.is_pr_commit = commit_meta_data.get("is_pr_commit", False)
        commit_model.files_changed = commit_meta_data.get("files_changed", 0)
        commit_model.is_revert_commit = commit_meta_data.get("is_revert_commit", False)

        return commit_model
