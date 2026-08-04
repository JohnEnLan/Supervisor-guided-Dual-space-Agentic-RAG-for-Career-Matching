# V2 基线清单（W0 · 2026-08-04）

| 项 | 值 |
|---|---|
| git tag | `v2-baseline`（commit 见 tag 指向） |
| 后端测试基线 | **314 passed**（`pytest tests/ -q`，本机复核） |
| 前端基线 | 30 tests + typecheck + build 绿（W 前最后核验于任务 1 验收） |
| 分支 | langgraph |
| 双远端 | GitHub `origin` + 伯明翰 GitLab，基线 commit 已同步 |

## 数据库备份状态：**已补做（2026-08-05）**

用户关闭 Smart App Control 后 pgvector 恢复（向量查询验证通过），备份立即补做完成，下表已填实。以下为原始受阻记录（留档）：

计划的 `pg_dump` 基线备份（仓库外受控目录 `Desktop/毕业论文_birmingham/backups/db/`，仅 hash 入库）当前无法执行：

- 阻断原因：Windows **Smart App Control（强制模式）** 拦截未签名的 `C:/Program Files/PostgreSQL/17/lib/vector.dll`，任何新建数据库连接的 pgvector 查询与 pg_dump 均失败（`An Application Control policy has blocked this file`）。
- 影响面：向量检索（dense/双空间/RAPTOR）在新连接上全部不可用；W5 灌库与 E2E 被同一问题阻断。
- 解除方式（需用户手动，属系统安全设置）：Windows 安全中心 → 应用和浏览器控制 → Smart App Control → 关闭（注意：关闭后无法重新开启，除非重装系统），或为该 DLL 配置 WDAC 例外。
- 解除后补做：`pg_dump --format=custom` → SHA-256 记入本清单。

## 备份留位

| 文件 | SHA-256 | 大小 | 状态 |
|---|---|---|---|
| `backups/db/v2-baseline-20260805.dump`（仓库外） | `6CEAD068D43D6325C5022B09B00E089D75C3E9C6A96510424F0074E143FB3739` | 1,863,041 B | ✅ 完成 |
