"""Agent 基类。

核心理念：一个 Agent 不是一个服务，而是【读 state → 拼 prompt → 调 LLM → 写回 state】。
三个业务 Agent 都继承它，只改 system prompt 和 build_user_prompt / parse 逻辑。
"""
from __future__ import annotations
import json
from abc import ABC, abstractmethod
from app.state.schema import SharedState
from app.llm import deepseek


class BaseAgent(ABC):
    name: str = "base"
    system_prompt: str = ""
    use_pro_model: bool = False

    @abstractmethod
    def build_user_prompt(self, state: SharedState) -> str:
        """从 state 里取需要的字段，拼成给 LLM 的输入。"""
        ...

    @abstractmethod
    def apply(self, state: SharedState, parsed: dict) -> SharedState:
        """把 LLM 输出写回 state 的对应子状态。"""
        ...

    async def run(self, state: SharedState) -> SharedState:
        user = self.build_user_prompt(state)
        raw = await deepseek.chat(
            self.system_prompt, user, pro=self.use_pro_model, json_mode=True
        )
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            # 失败时记录，交给 Supervisor 的 repair loop 处理，不要静默吞掉
            state.supervisor_log.append(
                {"agent": self.name, "error": "invalid_json", "raw": raw[:500]}
            )
            return state
        return self.apply(state, parsed)
