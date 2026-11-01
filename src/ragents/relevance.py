"""Skill, hafıza ve MCP seçiminde deterministik anahtar sözcük eşleşmesi."""
import re
from collections.abc import Iterable


def keywords_match(keywords: Iterable[str], prompt: str) -> bool:
    words = set(re.findall(r"\w+", prompt.casefold()))
    return any(set(re.findall(r"\w+", keyword.casefold())) <= words
               for keyword in keywords if keyword.strip())
