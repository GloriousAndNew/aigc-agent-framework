# AIGC Agent Framework

一个无需显卡、无需 API Key 的多媒体智能体框架起点。当前实现的是生成任务底座，尚未接入 LLM 规划器或真实媒体生成服务。

## 当前能力

- 图片、视频、音频三类任务，共用 Provider 协议。
- 本地 JSON API：提交任务、查询状态、健康检查。
- SQLite 保存请求、结果和状态；输出目录按任务隔离。
- 有界任务队列，默认最多 100 个未完成任务、2 个模拟执行线程。
- 服务重启时将未完成任务标为 interrupted，避免重复调用收费服务。
- MIT 许可证；零运行时第三方依赖。

MockProvider 只生成 `result.json` 测试清单，**不会生成真实图片、视频或音频**。模拟并发不代表真实模型/API 并发能力。

## 快速启动

需要 Python 3.10 或更高版本，在此项目目录运行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m aigc_agent.server
```

另一终端提交任务：

```powershell
$body = @{ kind = 'video'; prompt = '制作一段咖啡宣传视频' } | ConvertTo-Json
$task = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/tasks' -ContentType 'application/json; charset=utf-8' -Body ([System.Text.Encoding]::UTF8.GetBytes($body))
Invoke-RestMethod -Uri ('http://127.0.0.1:8000/tasks/' + $task.id)
```

状态为 queued → running → succeeded / failed；重启中断的任务为 interrupted。
数据库和模拟输出位于 `data/`，不纳入 Git。

## 不安装包也可以运行

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m aigc_agent.server
python -m unittest discover -s tests -v
```

## 接入真实服务

实现 `Provider.generate(request, output_dir) -> dict`，然后传给 `Engine(provider=YourProvider())`。
Provider 应把文件写入该任务目录，返回可 JSON 序列化的素材元数据。
真实实现需要配置网络超时、服务侧任务 ID、速率限制，以及凭证环境变量。
凭证不要写进请求、数据库或结果。

推荐按顺序扩展：

1. 接入一个图片生成 API，验证真实文件下载、超时与错误处理。
2. 接入 TTS API 和异步视频 API；保存远程任务 ID，避免重复计费。
3. 接入 LLM 生成结构化脚本/分镜，增加用户确认节点。
4. 增加项目、镜头、素材表及镜头级重生成，使用 FFmpeg 合成。
5. 需要长流程时接入 LangGraph；多人部署时更换为持久化分布式队列。

当前只绑定 127.0.0.1，用于单进程本地开发。同一数据目录只能由一个 Engine 实例管理。
尚未实现鉴权、多租户、取消任务、自动重试、分布式调度、Web 界面、成片合成或商业 API 适配器。
公网部署前需补齐身份验证、请求配额和生产 HTTP 服务。

## 测试

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m unittest discover -s tests -v
```

测试覆盖三类模拟任务、结果持久化、队列容量、Provider 失败及 HTTP 提交/查询/输入校验。
