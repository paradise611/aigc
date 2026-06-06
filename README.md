# 赛博错题医生

面向学生错题复盘的 AI 思维诊疗原型。项目根据参赛文档实现了三个核心模块：

- 主聊天页面：支持文本错题问诊、图片上传入口、AI 诊疗式回复。
- 聊天历史记录：保存每次问诊会话，支持查看历史对话。
- 错题分析页面：生成结构化错题档案，按学科和错因筛选错题本。

## 技术栈

- 前端：HTML + CSS + JavaScript
- 后端：Python + Flask
- LLM：OpenAI SDK，支持 OpenAI 或 OpenAI-compatible API
- 数据：本地 JSON 文件持久化，默认写入 `data/cyber_mistake_doctor.json`

## 启动项目

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python backend\app.py
```

打开浏览器访问：

```text
http://127.0.0.1:5000
```

## 接入真实 LLM

不配置密钥时，系统会自动使用本地规则生成演示版诊疗结果，便于比赛现场直接展示。

如需接入真实大模型：

```powershell
$env:OPENAI_API_KEY="你的 API Key"
$env:OPENAI_MODEL="gpt-4.1-mini"
python backend\app.py
```

如果使用兼容 OpenAI 接口的模型服务：

```powershell
$env:OPENAI_API_KEY="你的 API Key"
$env:OPENAI_BASE_URL="https://你的服务地址/v1"
$env:OPENAI_MODEL="你的模型名"
python backend\app.py
```

## API 概览

- `GET /api/health`：查看服务和模型状态
- `POST /api/chat`：发送错题问诊消息
- `GET /api/history`：获取聊天历史列表
- `GET /api/history/<session_id>`：获取单次会话详情
- `DELETE /api/history/<session_id>`：删除会话及关联错题
- `POST /api/analyze`：直接生成错题分析档案
- `GET /api/mistakes`：获取错题本，支持 `subject`、`error_type` 筛选

## 项目结构

```text
backend/
  app.py
frontend/
  index.html
  styles.css
  app.js
data/
  cyber_mistake_doctor.json
requirements.txt
README.md
```
