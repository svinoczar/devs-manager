from ast import Dict
from collections import defaultdict
from typing import Any

from src.data.enums.analytics import COMMENT_SYMBOLS
from src.data.enums.language import COMMENT_PATTERNS


async def count_meaningful_diff(diff_content: str) -> Dict[str, Any]:
    """Count meaningful additions and deletions in diff."""
    if not diff_content:
        return {
            "meaningful_additions": 0,
            "meaningful_deletions": 0,
            "top_files_by_additions": []
        }

    meaningful_additions = 0
    meaningful_deletions = 0
    file_additions = defaultdict(int)
    current_file = None

    lines = diff_content.split('\n')
    for line in lines:
        if line.startswith('diff --git'):
            # Extract filename from diff header
            parts = line.split()
            if len(parts) >= 3:
                current_file = parts[2].replace('a/', '').replace('b/', '')
        elif line.startswith('+') and not line.startswith('+++'):
            # Addition line
            if current_file:
                file_extension = current_file.split('.')[-1] if '.' in current_file else ''
                if not await self.is_comment_line(line[1:], file_extension):
                    meaningful_additions += 1
                    file_additions[current_file] += 1
        elif line.startswith('-') and not line.startswith('---'):
            # Deletion line
            if current_file:
                file_extension = current_file.split('.')[-1] if '.' in current_file else ''
                if not await self.is_comment_line(line[1:], file_extension):
                    meaningful_deletions += 1

    # Get top files by additions
    top_files = sorted(file_additions.items(), key=lambda x: x[1], reverse=True)[:5]

    return {
        "meaningful_additions": meaningful_additions,
        "meaningful_deletions": meaningful_deletions,
        "top_files_by_additions": [{"file": file, "additions": count} for file, count in top_files]
    }
    
async def is_comment_line(line: str, file_extension: str) -> bool:
    """Check if line is a comment using language-specific patterns."""
    if not line.strip():
        return False

    # Get language-specific comment patterns
    lang_patterns = COMMENT_PATTERNS.get(file_extension, {})
    single_line = lang_patterns.get('single_line', [])
    multi_line_start = lang_patterns.get('multi_line_start', [])

    # Check for single-line comments
    for symbol in single_line:
        if line.strip().startswith(symbol):
            return True

    # Check for multi-line comment starts
    for symbol in multi_line_start:
        if line.strip().startswith(symbol):
            return True

    # Fallback to legacy COMMENT_SYMBOLS for backward compatibility
    symbols = COMMENT_SYMBOLS.get(file_extension, [])
    for symbol in symbols:
        if line.strip().startswith(symbol):
            return True

    return False 