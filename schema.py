"""Shared Structured State — 单一事实来源。

所有 Agent 读写同一个结构。新增字段先改这里，不要在各 Agent 里临时造字段。
状态本身不持有任何业务逻辑，只是一个被 Postgres 序列化/反序列化的容器。
"""
from __future__ import annotations
from pydantic import BaseModel, Field


class ResumeState(BaseModel):
    education: list[dict] = Field(default_factory=list)
    experience: list[dict] = Field(default_factory=list)
    projects: list[dict] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    resume_quality_issues: list[str] = Field(default_factory=list)
    # 禁止编造的依据：后续 Agent 写简历建议只能基于这里的原文片段
    original_evidence_spans: list[dict] = Field(default_factory=list)
    normalized_base_resume: str = ""


class CareerState(BaseModel):
    current_goal: list[str] = Field(default_factory=list)
    long_term_goal: list[str] = Field(default_factory=list)
    hard_constraints: dict = Field(default_factory=dict)   # 走 SQL 过滤
    soft_preferences: dict = Field(default_factory=dict)   # 走排序加权
    avoid_roles: list[str] = Field(default_factory=list)


class RetrievalState(BaseModel):
    candidate_job_ids: list[str] = Field(default_factory=list)
    filter_log: list[str] = Field(default_factory=list)
    ranking_scores: list[dict] = Field(default_factory=list)
    evidence_span_ids: list[str] = Field(default_factory=list)


class StrategyState(BaseModel):
    # 每条 recommended_role 带 tier: "now_fit" | "stretch_fit" | "bridge_role"
    recommended_roles: list[dict] = Field(default_factory=list)
    resume_revision_plan: list[dict] = Field(default_factory=list)
    career_path: list[dict] = Field(default_factory=list)
    skill_gap_analysis: list[dict] = Field(default_factory=list)


class FeedbackState(BaseModel):
    application_history: list[dict] = Field(default_factory=list)
    interview_outcomes: list[dict] = Field(default_factory=list)
    user_feedback: list[dict] = Field(default_factory=list)


class SharedState(BaseModel):
    session_id: str
    user_id: str
    resume_state: ResumeState = Field(default_factory=ResumeState)
    career_state: CareerState = Field(default_factory=CareerState)
    retrieval_state: RetrievalState = Field(default_factory=RetrievalState)
    strategy_state: StrategyState = Field(default_factory=StrategyState)
    feedback_state: FeedbackState = Field(default_factory=FeedbackState)
    # 每次核查/触发 bounded loop 的记录，答辩时用来讲"Supervisor 做了什么"
    supervisor_log: list[dict] = Field(default_factory=list)
