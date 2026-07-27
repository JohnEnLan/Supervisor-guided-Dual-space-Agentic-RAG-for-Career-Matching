# Windows 一键启动器设计

## 目标

为 Career-RAG 提供一个可直接双击的 Windows 启动入口。启动器负责完成必要检查、数据库迁移、前后端启动与浏览器打开，同时保留两个可见终端窗口，方便用户查看日志和停止服务。

## 范围

本改动只增加本地开发启动脚本及对应测试，不改变 FastAPI、React、PostgreSQL、Agent 工作流或部署架构。

## 文件

- `start.bat`：面向用户的双击入口，使用仓库根目录定位 `start.ps1`。
- `start.ps1`：执行检查、迁移、端口检查、子窗口启动、就绪等待和浏览器打开。
- `tests/test_windows_launcher.py`：验证入口文件和无副作用检查模式。

## 启动流程

1. 用户双击仓库根目录中的 `start.bat`。
2. BAT 使用 `powershell.exe -NoProfile -ExecutionPolicy Bypass` 调用同目录的 `start.ps1`，避免依赖 `.ps1` 文件关联，并只对当前进程绕过执行策略。
3. PowerShell 根据 `$PSScriptRoot` 定位仓库，不依赖用户当前工作目录，因此可处理路径中的中文和空格。
4. 启动器验证以下项目：
   - `.env` 存在；
   - `.venv\Scripts\python.exe` 存在；
   - `npm.cmd` 可用；
   - `frontend\package.json` 存在；
   - `frontend\node_modules` 存在；
   - 本机端口 `8000` 和 `5173` 未被占用。
5. 启动器在当前窗口同步运行 `python -m app.db.migrate`。迁移失败时显示错误、暂停并退出，不启动任何子服务。
6. 启动器分别打开两个可见 PowerShell 窗口：
   - `Career-RAG Backend`：在仓库根目录运行 `python -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000 --reload`。
   - `Career-RAG Frontend`：在 `frontend` 目录运行 `npm.cmd run dev`。
7. 主启动窗口轮询 `http://127.0.0.1:8000/docs` 和 `http://127.0.0.1:5173`。每个服务最多等待 60 秒。
8. 前端就绪后，使用系统默认浏览器打开 `http://127.0.0.1:5173`。
9. 启动窗口显示成功信息后退出；两个服务窗口继续保持。用户可在相应窗口按 `Ctrl+C` 停止服务。

## 错误处理

- 缺少 `.env` 时，提示从 `.env.example` 复制并填写。
- 缺少虚拟环境或后端依赖入口时，提示创建虚拟环境并安装 `requirements.txt`。
- 缺少 npm 时，提示安装 Node.js。
- 缺少 `node_modules` 时，提示在 `frontend` 下执行 `npm.cmd install`；启动器不自动联网安装依赖。
- 端口被占用时，启动器在创建子窗口前退出，避免重复服务和端口漂移。
- 数据库连接或迁移失败时，保留完整命令输出并退出。
- 服务在 60 秒内未就绪时，提示用户检查对应服务窗口；不自动终止已启动的服务。

## 检查模式

`start.ps1 -CheckOnly` 只执行文件、工具与端口检查，并输出计划启动的组件；不执行数据库迁移、不创建子进程，也不打开浏览器。该模式用于自动化测试和故障排查。

## 测试策略

测试通过 Python `pytest` 调用真实 PowerShell 脚本：

1. 验证 `start.bat` 使用自身目录调用 `start.ps1`。
2. 在项目当前环境中运行 `start.ps1 -CheckOnly`，断言退出码为零，并确认不会启动服务。
3. 验证 PowerShell 脚本可以被解析，且检查模式包含前后端启动计划。

测试不调用外部 API、不执行数据库写入、不打开浏览器。

## 验收标准

- 双击 `start.bat` 能打开两个命名明确的可见终端窗口。
- 后端监听 `127.0.0.1:8000`，前端监听 `127.0.0.1:5173`。
- 数据库迁移在后端启动前完成。
- 前端就绪后自动打开默认浏览器。
- 常见环境问题有可操作的中文错误提示。
- 检查模式及相关测试通过，且不会留下后台进程。
