from dataclasses import replace
import json

from pydantic_ai.messages import (
    ModelMessage, ModelMessagesTypeAdapter, ModelRequest, ModelResponse,
    TextPart, ToolReturnPart, UserPromptPart,
)

from ragents.contracts import ContextUsage, RunRequest
from ragents.errors import ContextLimitError


class ContextGuard:
    def __init__(self, request: RunRequest, *, extra_chars: int = 0):
        self.policy = request.agent.context
        self.instructions = request.agent.instructions
        self.extra_chars = extra_chars
        self.dropped_turns = 0
        self.trimmed_tool_results = 0
        self.peak_request_chars = 0

    def size(self, messages: list[ModelMessage]) -> int:
        return self.extra_chars + len(self.instructions) + len(ModelMessagesTypeAdapter.dump_json(messages).decode("utf-8"))

    def history(self, request: RunRequest) -> list[ModelMessage]:
        keep = self.policy.max_history_turns
        turns = request.history[-keep:] if keep else ()
        self.dropped_turns = len(request.history) - len(turns)
        messages: list[ModelMessage] = []
        for turn in turns:
            messages.extend([
                ModelRequest(parts=[UserPromptPart(turn.prompt)]),
                ModelResponse(parts=[TextPart(turn.output)]),
            ])
        current = ModelRequest(parts=[UserPromptPart(request.prompt)])
        while messages and self.size([*messages, current]) > self.policy.max_request_chars:
            del messages[:2]
            self.dropped_turns += 1
        return messages

    def process(self, messages: list[ModelMessage]) -> list[ModelMessage]:
        bounded = [self.trim_tools(message) for message in messages]
        size = self.size(bounded)
        self.peak_request_chars = max(size, self.peak_request_chars)
        if size > self.policy.max_request_chars:
            raise ContextLimitError()
        return bounded

    def trim_tools(self, message: ModelMessage) -> ModelMessage:
        if not isinstance(message, ModelRequest):
            return message
        parts = []
        for part in message.parts:
            if isinstance(part, ToolReturnPart):
                content = part.content if isinstance(part.content, str) else json.dumps(part.content, ensure_ascii=False)
                if len(content) > self.policy.max_tool_output_chars:
                    suffix = "\n[araç çıktısı kısaltıldı]"
                    part = replace(part, content=content[:self.policy.max_tool_output_chars - len(suffix)] + suffix)
                    self.trimmed_tool_results += 1
            parts.append(part)
        return replace(message, parts=parts)

    def report(self) -> ContextUsage:
        return ContextUsage(
            dropped_turns=self.dropped_turns, trimmed_tool_results=self.trimmed_tool_results,
            peak_request_chars=self.peak_request_chars,
        )
