# B4 视觉 OCR 兜底——批次验收记录（2026-08-09）

## 范围

B3 封版 173e018 → B4 终审修复完成（含整批终审两侧意见处置）。执行模式：
细化方案 v3 三方收敛（子 agent 三轮 / Codex 四轮）→ Codex 分模块执行
（M2a/M2b+M2c/M3/M4）→ 协调者逐模块验收 → 整批终审（子 agent PASS +
Codex 5M/4m 全部处置）。

## 被测 SHA 与命令（Codex 终审二/三轮补录）

- 被测提交链（固定 SHA）：`ab9e06b`（终审一轮 5M/4m 修复）→ `29b5b27`
  （MPO 放宽）→ `5e7ffeb`（终审二轮 minor）→ 本文件所在的收尾提交
  （文档/注释级，无代码语义变更；封版提交信息含 "B4 SEALED"）。
- 命令（Windows PowerShell 5.1，仓库根目录逐条执行）：
  - `.\.venv\Scripts\python.exe -m pytest tests -p no:cacheprovider --basetemp="C:\Users\WIN11\AppData\Local\Temp\crtest_b4_accept" -q`
    （basetemp 必须是短路径下的全新目录名，规避 MAX_PATH 与残留 ACL）
  - `Set-Location frontend; npm test; npm run typecheck; npm run build; Set-Location ..`
    （PowerShell 5.1 无 `&&`，分号顺序执行即可——各命令失败会自行非零退出）
  - `.\.venv\Scripts\python.exe scripts\export_openapi.py`（快照再生）随后
    `.\.venv\Scripts\python.exe -m pytest tests\test_api_v1.py::test_openapi_v1_snapshot_is_current -p no:cacheprovider --basetemp="C:\Users\WIN11\AppData\Local\Temp\crtest_b4_snap" -q`

## 四门实测（终审修复后，本机）

- 后端 pytest：**736 passed, 0 failed**（含 test_resume_ocr.py 41 项、
  test_extraction_golden.py 15 项 golden 逐字节守卫、test_qwen_vl.py 6 项）
- 前端 vitest：**134 passed（14 文件）**
- tsc：0 错
- vite build：成功；OpenAPI 快照 + generated.ts + fixtures 再生一致

（736 = 终审修复轮最终值；过程节点 691→695→732→733→736。）

## 真实模型冒烟

见 `2026-08-09-b4-vl-smoke.md`（qwen-vl-ocr 实调 PASS，唯一一次真实 VL
调用；其余测试全 mock）。

## 终审关键处置（详情见方案文档与提交信息）

- 伪装格式拒绝：真实容器必须匹配后缀（GIF 改名混不进解码管线）。
- prep 并发闸：解码/光栅化/编码与 VL 网络闸分离限流，内存峰值有界。
- VL 墙钟：httpx 分段超时之上加 asyncio.wait_for 总时限 90s；
  external_started 由 VL 边界在传输紧前回调置位。
- flag=false 闭环：图片白名单/固定 preview/0 页 PDF 422 全部随开关；
  开启期上传的图片在关闭后确认解析 → 409 resume_ocr_disabled（扣额度前
  拒绝）。
- 部署 env 追加幂等化（grep 守卫），防覆盖运维手调值。
