"""P2 — RAPTOR 离线层级树（先留接口）。
离线：JD chunk -> job summary -> role cluster summary -> career direction cluster。
在线：先检索高层 summary 再下钻到 chunk，降低全库 dense 检索成本。
时间不够则不实现，只在论文写"接口已预留"。
"""
# TODO(P2)
