from typing import Annotated

from pydantic import Field


def text_stats(text: Annotated[str, Field(max_length=8000)]) -> dict[str, int]:
    """Metindeki karakter ve boşlukla ayrılmış sözcük sayısını hesapla."""
    return {"characters": len(text), "words": len(text.split())}


TOOL_HANDLERS = {"text_stats": text_stats}
