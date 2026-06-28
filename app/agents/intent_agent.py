"""Stage 1 — Intent & Career Profile Agent。
职责：从 base resume + 用户输入中提取 current_goal / long_term_goal /
      hard_constraints / soft_preferences / avoid_roles，写入 career_state。
关键：区分硬约束(签证/地点/经验) 与软偏好(行业/技术栈兴趣)；不要过度推断长期目标。
继承 BaseAgent，只需写 system_prompt + build_user_prompt + apply。
"""
from app.agents.base import BaseAgent
# TODO(P0): 实现
