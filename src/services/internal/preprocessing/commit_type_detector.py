from collections import defaultdict
import fnmatch
import re

from src.data.github_api_response.commits_response_entity import SingleCommitEntity
from src.data.domain.commit import Commit
from src.data.enums.analytics import COMMIT_TYPE_PATTERNS, CONVENTIONAL_COMMIT_PATTERN


class HeuristicCommitClassifier:
    def detect(self, commit: SingleCommitEntity, analysis_settings: dict) -> dict:
        commit_sign = commit.commit
        msg = commit_sign.message.lower()
        commit_rules = analysis_settings.get("commit_rules", {})
        rules = commit_rules.get("rules", [])

        # commit_type
        default_category = commit_rules.get("default_category", "NO CATEGORY")
        matched_rule = default_category
        highest_priority = -1
        for rule in rules:
            for keyword in rule.get("keywords", []):
                if keyword.lower() in msg:
                    if rule.get("priority", 0) > highest_priority:
                        matched_rule = rule
                        highest_priority = rule.get("priority", 0)

        category = matched_rule
        commit_type = category

        # is_conventional
        is_conventional = category != "NO CATEGORY"

        # conventional_type
        conventional_type = category

        # conventional_scope
        conventional_scope = (
            re.search(r"^\w+:\s", msg)[0].split(":")[0]
            if re.search(r"^\w+:\s", msg) # browser: / api:
            else "no"
        )

        # is_breaking_change
        is_breaking_change = msg.startswith("!") or msg.startswith("breaking")

        # parents_count
        parents_count = len(commit.parents)

        # parents
        # parents = commit.parents

        # is_merge_commit
        is_merge_commit = parents_count > 1

        # is_pr_commit
        is_pr_commit = any([
            "merge pull request" in msg,
            "merge mr" in msg,
            re.search(r"#\d+", msg) is not None, # (#123) / #1467
            re.search(r"pull request", msg) is not None,
        ])

        # files_changed
        files_changed = len(commit.files) if commit.files else None

        # is_revert_commit
        is_revert_commit = (
            msg.startswith("revert")
            or msg.startswith("rollback")
            or "this reverts commit" in msg
        )

        return {
            "commit_type": commit_type,
            "is_conventional": is_conventional,
            "conventional_type": conventional_type,
            "conventional_scope": conventional_scope,
            "is_breaking_change": is_breaking_change,
            "parents_count": parents_count,
            "is_merge_commit": is_merge_commit,
            "is_pr_commit": is_pr_commit,
            "files_changed": files_changed,
            "is_revert_commit": is_revert_commit,
        }

        # return "unknown"
