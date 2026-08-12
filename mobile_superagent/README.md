# mobile_superagent

在**你自己的 Android 真机**上，用自然语言完成多步手机任务。支持 Web 下发、
过程回放、人工接管与定时执行。这是 android-harness 的**架构升级版**：从单
文件 web.py 演进为 FastAPI 多服务架构，并新增**视频链路**（截图 OCR 读取
抖音等视频画面字幕/标题，解决 uiautomator 读不到渲染层文字的问题）。

## 一句话
自然语言 → Agent 循环（每轮一个原子动作，观察→决策→执行→验证）→ 真机可验证 UI 操作。

## 架构
```
[Web Console] [CLI] [Telegram以后]
       \       |       /
        v      v      v
     API Gateway (FastAPI)
              |
     +--------+--------+
     |                 |
 Task Service   Routine Scheduler
     |                 |
     v                 v
 Agent Runtime  <-->  Queue
     |                 |
     +--------+--------+
              |
     Device Manager (adb/u2)
              |
        Android Phone(s)
```
MVP 单进程：FastAPI 内嵌后台 worker 线程 + 轮询 scheduler。

## 目录
```
mobile_superagent/
├── prompts/            # system.md + skills/*.md（技能按需加载）
├── app/
│   ├── main.py         # FastAPI 入口
│   ├── settings.py     # .env 配置
│   ├── db.py           # SQLite 数据层（devices/tasks/steps/routines/profile）
│   ├── api/            # devices / tasks / routines / profile
│   ├── worker/runner.py# 后台跑 AgentLoop
│   ├── scheduler/      # routines 轮询调度
│   └── core/           # agent_loop / perception / llm / schema / safety / progress / router / device_bridge / device_manager / skill_loader
├── cli.py
└── storage/            # app.db + runs/（截图、trace）
```

## 视频链路（新增）
FEED_SUMMARY 场景下，抖音等视频的**标题/字幕在渲染层**，uiautomator dump
读不到。`app/core/perception.py` 新增 `screen_ocr`：**截图 + Tesseract 中文 OCR**，
把画面可见文字（视频标题、话题、字幕）喂回 Agent，从而能真正"看懂"视频内容。
- tesseract 已装：`C:\Program Files\Tesseract-OCR\tesseract.exe`
- 中文语言包 chi_sim 放项目 `tessdata/`，通过 `TESSDATA_PREFIX` 指向
- 无需管理员权限（不写 Program Files）

## 启动
```bash
cd mobile_superagent
# 1. 配置 .env（复制 .env.example，填 LLM_API_KEY，key 只存本地）
cp .env.example .env

# 2. 装依赖
pip install -r requirements.txt

# 3. 启动 API
uvicorn app.main:app --reload --port 8000

# 4. 扫描设备
curl -X POST http://127.0.0.1:8000/api/devices/refresh

# 5. 跑任务（用返回的 device_id）
python cli.py --device-id <id> --goal "打开抖音浏览3个视频并摘要"
```

## 安全
- 每步动作走白名单 + SafetyGuard（代码强制：密码/支付/卸载拦截）
- 敏感步骤 request_user_takeover 转人工接管
- 无进展检测（UI 指纹 + 截图感知哈希）防死循环
- key 只存本地 `.env`，gitignore，绝不提交/打印

## 验收
- `uvicorn` 起来后 `/docs` 有完整 API 文档
- `curl http://127.0.0.1:8000/health` → `{"ok":true}`
