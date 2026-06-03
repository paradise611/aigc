import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from openai import OpenAI


BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
DATA_DIR = BASE_DIR / "data"
DATA_FILE = DATA_DIR / "cyber_mistake_doctor.json"

DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")

app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path="")


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def ensure_store():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not DATA_FILE.exists():
        DATA_FILE.write_text(
            json.dumps({"sessions": [], "mistakes": []}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def load_store():
    ensure_store()
    with DATA_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_store(store):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")


def get_or_create_session(store, session_id=None):
    if session_id:
        for session in store["sessions"]:
            if session["id"] == session_id:
                return session

    session = {
        "id": uuid.uuid4().hex,
        "title": "新的错题问诊",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "messages": [],
    }
    store["sessions"].insert(0, session)
    return session


def infer_subject(text):
    lower = text.lower()
    if any(token in text for token in ["函数", "方程", "导数", "几何", "概率", "矩阵"]) or re.search(r"\d+\s*[+\-*/=]", text):
        return "数学"
    if any(token in text for token in ["英语", "完形", "阅读", "语法", "单词"]):
        return "英语"
    if any(token in text for token in ["力", "电路", "速度", "加速度", "压强", "牛顿"]):
        return "物理"
    if any(token in text for token in ["化学", "反应", "离子", "方程式", "溶液"]):
        return "化学"
    if any(token in lower for token in ["python", "java", "算法", "代码", "递归"]):
        return "计算机"
    return "综合"


def infer_error_type(text):
    mapping = [
        ("概念混淆", ["概念", "定义", "性质", "公式", "定理", "不知道为什么"]),
        ("审题偏差", ["题意", "条件", "没看清", "问什么", "范围"]),
        ("步骤遗漏", ["漏", "少写", "跳步", "步骤", "过程"]),
        ("计算失误", ["算错", "计算", "符号", "小数", "单位"]),
        ("方法误用", ["方法", "套公式", "模型", "思路"]),
        ("逻辑跳跃", ["推不出", "为什么", "逻辑", "所以"]),
    ]
    for error_type, keys in mapping:
        if any(key in text for key in keys):
            return error_type
    return "思路不完整"


def extract_tags(text):
    candidates = ["函数", "方程", "几何", "概率", "导数", "阅读理解", "语法", "力学", "电路", "化学方程式", "算法"]
    tags = [tag for tag in candidates if tag in text]
    if not tags:
        tags = [infer_subject(text), infer_error_type(text)]
    return list(dict.fromkeys(tags))[:4]


def local_diagnosis(user_text):
    subject = infer_subject(user_text)
    error_type = infer_error_type(user_text)
    tags = extract_tags(user_text)
    focus = "、".join(tags)

    answer = (
        f"我先按“错题问诊”的方式帮你拆一下。\n\n"
        f"**初步判断**：这道题更像是{subject}问题，主要错误类型可能是「{error_type}」。"
        f"你现在的问题不是单纯缺答案，而是需要把题目条件、解题路径和错误发生点重新对齐。\n\n"
        f"**建议复盘路径**：\n"
        f"1. 先用一句话复述题目到底要求什么，圈出限制条件。\n"
        f"2. 把你的原解法按步骤写出来，标出第一处“不确定但继续往下做”的位置。\n"
        f"3. 对照标准思路，判断错误是来自概念、条件读取、方法选择还是计算执行。\n"
        f"4. 做一道同知识点的变式题，确认不是“看懂答案”式的假会。\n\n"
        f"**我想追问你一个关键点**：你当时是从哪个条件开始想到这个方法的？"
        f"如果你把原题和自己的解题步骤补充给我，我可以继续定位到具体错误节点。"
    )

    mistake = {
        "id": uuid.uuid4().hex,
        "title": build_title(user_text),
        "subject": subject,
        "error_type": error_type,
        "tags": tags,
        "question": user_text,
        "wrong_step": "等待用户补充原始作答步骤",
        "root_cause": f"疑似{error_type}，需要结合原解题过程进一步确认。",
        "correct_idea": "先明确题目目标与条件，再选择对应方法，最后用反例或代入检验。",
        "training_plan": [
            f"复盘 {focus} 的核心定义和适用条件",
            "整理本题的条件清单与解题分支",
            "完成 2 道同类变式题并记录第一反应",
        ],
        "created_at": now_iso(),
    }
    return answer, mistake


def build_title(text):
    cleaned = re.sub(r"\s+", " ", text).strip()
    cleaned = re.sub(r"[#*_`>]+", "", cleaned)
    return (cleaned[:22] + "...") if len(cleaned) > 24 else cleaned or "未命名错题"


def call_llm(user_text, history):
    if not os.getenv("OPENAI_API_KEY"):
        return None

    client_kwargs = {}
    if OPENAI_BASE_URL:
        client_kwargs["base_url"] = OPENAI_BASE_URL
    client = OpenAI(**client_kwargs)

    messages = [
        {
            "role": "system",
            "content": (
                "你是“赛博错题医生”，一个面向学生的错题思维诊疗助手。"
                "不要只给答案，要定位错误行为、解释根因、用苏格拉底式问题引导学生复盘。"
                "输出包含：初步诊断、错误可能发生点、正确思路、追问、复习建议。"
            ),
        }
    ]
    for item in history[-8:]:
        messages.append({"role": item["role"], "content": item["content"]})
    messages.append({"role": "user", "content": user_text})

    response = client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=messages,
        temperature=0.4,
    )
    return response.choices[0].message.content


@app.get("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.get("/<path:path>")
def static_files(path):
    return send_from_directory(FRONTEND_DIR, path)


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "model": DEFAULT_MODEL, "llm_enabled": bool(os.getenv("OPENAI_API_KEY"))})


@app.get("/api/history")
def history():
    store = load_store()
    sessions = [
        {
            "id": s["id"],
            "title": s["title"],
            "created_at": s["created_at"],
            "updated_at": s["updated_at"],
            "message_count": len(s["messages"]),
            "preview": next((m["content"] for m in reversed(s["messages"]) if m["role"] == "assistant"), ""),
        }
        for s in store["sessions"]
    ]
    return jsonify({"sessions": sessions})


@app.get("/api/history/<session_id>")
def session_detail(session_id):
    store = load_store()
    session = next((s for s in store["sessions"] if s["id"] == session_id), None)
    if not session:
        return jsonify({"error": "session not found"}), 404
    return jsonify(session)


@app.post("/api/chat")
def chat():
    payload = request.get_json(force=True) or {}
    user_text = (payload.get("message") or "").strip()
    session_id = payload.get("session_id")

    if not user_text:
        return jsonify({"error": "message is required"}), 400

    store = load_store()
    session = get_or_create_session(store, session_id)
    session["messages"].append({"role": "user", "content": user_text, "created_at": now_iso()})
    if session["title"] == "新的错题问诊":
        session["title"] = build_title(user_text)

    local_answer, mistake = local_diagnosis(user_text)

    try:
        answer = call_llm(user_text, session["messages"])
        if answer is None:
            answer = local_answer
    except Exception as exc:
        answer = local_answer
        answer += f"\n\n（真实 LLM 调用失败，已切换本地诊疗模式：{exc}）"

    mistake["session_id"] = session["id"]
    store["mistakes"].insert(0, mistake)

    session["messages"].append({"role": "assistant", "content": answer, "created_at": now_iso()})
    session["updated_at"] = now_iso()
    save_store(store)

    return jsonify({"session_id": session["id"], "reply": answer, "mistake": mistake})


@app.get("/api/mistakes")
def mistakes():
    store = load_store()
    subject = request.args.get("subject", "").strip()
    error_type = request.args.get("error_type", "").strip()
    items = store["mistakes"]
    if subject:
        items = [item for item in items if item.get("subject") == subject]
    if error_type:
        items = [item for item in items if item.get("error_type") == error_type]
    return jsonify({"mistakes": items})


@app.post("/api/analyze")
def analyze():
    payload = request.get_json(force=True) or {}
    text = (payload.get("question") or payload.get("message") or "").strip()
    if not text:
        return jsonify({"error": "question is required"}), 400
    answer, mistake = local_diagnosis(text)
    store = load_store()
    store["mistakes"].insert(0, mistake)
    save_store(store)
    return jsonify({"analysis": answer, "mistake": mistake})


@app.delete("/api/history/<session_id>")
def delete_session(session_id):
    store = load_store()
    before = len(store["sessions"])
    store["sessions"] = [s for s in store["sessions"] if s["id"] != session_id]
    store["mistakes"] = [m for m in store["mistakes"] if m.get("session_id") != session_id]
    save_store(store)
    return jsonify({"deleted": before - len(store["sessions"])})


if __name__ == "__main__":
    ensure_store()
    app.run(
        host="127.0.0.1",
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG") == "1",
        use_reloader=False,
    )
