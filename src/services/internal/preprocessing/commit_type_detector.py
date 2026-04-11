import re

from src.data.github_api_response.commits_response_entity import SingleCommitEntity

# Conventional commit pattern: type(scope): description
CONVENTIONAL_COMMIT_RE = re.compile(
    r"^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)"
    r"(\([a-z0-9_\-]+\))?"
    r"(!)?:\s",
    re.IGNORECASE,
)

# Word-boundary keyword matching — avoids "sessions" matching "test", "fix" matching "suffix", etc.
def _word_match(keyword: str, text: str) -> bool:
    """Check if keyword appears as a whole word in text."""
    # Short keywords (<=3 chars) require word boundaries; longer ones can use substring
    if len(keyword) <= 3:
        pattern = r"\b" + re.escape(keyword) + r"\b"
        return bool(re.search(pattern, text, re.IGNORECASE))
    return keyword.lower() in text.lower()


class HeuristicCommitClassifier:
    def detect(self, commit: SingleCommitEntity, settings: dict) -> dict:
        commit_sign = commit.commit

        # !! IMPORTANT: Only use the FIRST LINE of the commit message.
        # Using the full body causes false positives, e.g. a commit titled
        # "sessions - show changes as tree" whose body mentions "test coverage"
        # would be incorrectly tagged as "test".
        first_line = commit_sign.message.split("\n")[0]
        msg_first = first_line.lower()

        commit_rules = settings.get("commit_rules", {})
        rules = commit_rules.get("rules", [])
        default_category = commit_rules.get("default_category", "NO CATEGORY")

        # --- Structural characteristics ---
        parents_count = len(commit.parents)

        is_merge_commit = (
            parents_count > 1
            or msg_first.startswith("merge")
            or "merge branch" in msg_first
            or "merge remote-tracking branch" in msg_first
            or "merge pull request" in msg_first
            or "merge mr" in msg_first
        )

        is_revert_commit = (
            msg_first.startswith("revert")
            or msg_first.startswith("rollback")
            or "this reverts commit" in msg_first
        )

        # PR commit: references a PR number like (#123) or "pull request"
        is_pr_commit = bool(
            re.search(r"\(#\d+\)", msg_first)          # (#123) — PR reference in parens
            or "pull request" in msg_first
            or "merge pull request" in msg_first
            or "merge mr" in msg_first
        )

        files_changed = len(commit.files) if commit.files else None

        # --- Commit type detection ---
        if is_merge_commit:
            commit_type = "merge"
            category = "merge"
        elif is_revert_commit:
            commit_type = "revert"
            category = "revert"
        else:
            # 1. Try conventional commit format first (most reliable)
            conv_match = CONVENTIONAL_COMMIT_RE.match(first_line)
            if conv_match:
                raw_type = conv_match.group(1).lower()
                # Normalize some aliases
                type_map = {
                    "feat": "feat",
                    "fix": "fix",
                    "docs": "docs",
                    "style": "style",
                    "refactor": "refactor",
                    "perf": "perf",
                    "test": "test",
                    "build": "build",
                    "ci": "build",
                    "chore": "chore",
                    "revert": "revert",
                }
                category = type_map.get(raw_type, raw_type)
                commit_type = category
            else:
                # 2. Keyword matching against config rules
                matched_rule = None
                highest_priority = -1
                for rule in rules:
                    for keyword in rule.get("keywords", []):
                        if _word_match(keyword, msg_first):
                            if rule.get("priority", 0) > highest_priority:
                                matched_rule = rule
                                highest_priority = rule.get("priority", 0)

                category = matched_rule.get("category", default_category) if matched_rule else default_category
                commit_type = category

        is_conventional = CONVENTIONAL_COMMIT_RE.match(first_line) is not None
        conventional_type = category

        conventional_scope_match = re.match(r"^\w+\(([a-z0-9_\-]+)\):", first_line, re.IGNORECASE)
        conventional_scope = conventional_scope_match.group(1) if conventional_scope_match else "no"

        # Breaking change: conventional "!" marker or explicit keyword
        is_breaking_change = (
            bool(re.match(r"^\w+(\([^)]+\))?!:", first_line))
            or msg_first.startswith("breaking change")
            or "breaking change" in msg_first
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
