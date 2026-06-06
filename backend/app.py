import base64
import io
import json
import os
import re
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path

import requests
from flask import Flask, jsonify, request, send_from_directory
from PIL import Image

# 加载 .env 文件
try:
    from dotenv import load_dotenv
    BASE_DIR = Path(__file__).resolve().parent.parent
    load_dotenv(BASE_DIR / ".env")
except Exception:
    BASE_DIR = Path(__file__).resolve().parent.parent

FRONTEND_DIR = BASE_DIR / "frontend"
DATA_DIR = BASE_DIR / "data"
DATA_FILE = DATA_DIR / "cyber_mistake_doctor.json"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

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
        f"初步判断：这道题更像是{subject}问题，主要错误类型可能是「{error_type}」。"
        f"你现在的问题不是单纯缺答案，而是需要把题目条件、解题路径和错误发生点重新对齐。\n\n"
        f"建议复盘路径：\n"
        f"1. 先用一句话复述题目到底要求什么，圈出限制条件。\n"
        f"2. 把你的原解法按步骤写出来，标出第一处“不确定但继续往下做”的位置。\n"
        f"3. 对照标准思路，判断错误是来自概念、条件读取、方法选择还是计算执行。\n"
        f"4. 做一道同知识点的变式题，确认不是“看懂答案”式的假会。\n\n"
        f"我想追问你一个关键点：你当时是从哪个条件开始想到这个方法的？"
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


def call_gemini(user_text, history, image_base64=None):
    """调用 Google Gemini 进行诊断（支持文本和图片）"""
    if not GEMINI_API_KEY:
        return None

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"

    system_prompt = (
        '你是"赛博错题医生"，一个面向学生的AI认知教练。你的核心任务不是直接给答案，而是：\n\n'
        '诊療流程：\n'
        '1. 初步诊断：快速判断题目学科、知识点和难度\n'
        '2. 错误定位：如果用户提供了作答过程，精准定位第一处错误节点\n'
        '3. 根因分析：区分错误类型——概念混淆/审题偏差/步骤遗漏/逻辑跳跃/计算失误/方法误用\n'
        '4. 苏格拉底式追问：不要直接说「你错了」，而是用提问引导反思\n'
        '5. 认知修复：给出正确思路，但要强调理解而非记忆\n'
        '6. 巩固建议：推荐同类变式题的解题策略\n\n'
        '输出时请使用纯文本格式，不要使用Markdown语法（不要用 ###、**、* 等符号）。\n'
        '用emoji和自然换行来组织内容结构即可。示例：\n'
        '🔍 初步诊断：学科/知识点/难度\n'
        '❌ 错误定位：第几步出了问题\n'
        '🧠 根因分析：为什么出错（认知层面）\n'
        '💬 追问引导：1-2个引导学生反思的问题\n'
        '✅ 正确思路：清晰的分步解答\n'
        '📚 巩固建议：同类题策略 + 知识点梳理\n\n'
        '核心原则：\n'
        '- 永远保持鼓励和耐心，像一位好老师\n'
        '- 引导学生自己发现错误，而非直接指出\n'
        '- 关注思维过程，而非仅仅答案对错\n'
        '- 用通俗语言解释复杂概念'
    )

    # 构建对话历史
    contents = []
    for item in history[-8:]:
        role = "model" if item["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": item["content"]}]})

    # 构建当前用户消息
    if image_base64:
        parts = [
            {"text": user_text or "请识别这张图片中的题目，并进行分析。"},
            {"inline_data": {"mime_type": "image/jpeg", "data": image_base64}},
        ]
    else:
        parts = [{"text": user_text}]
    contents.append({"role": "user", "parts": parts})

    body = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
    }

    resp = requests.post(url, json=body, timeout=60)
    data = resp.json()

    if "candidates" in data and len(data["candidates"]) > 0:
        candidate = data["candidates"][0]
        if "content" in candidate and "parts" in candidate["content"]:
            return candidate["content"]["parts"][0].get("text", None)
    return None


def generate_statistics(store):
    """生成错题统计数据"""
    mistakes = store["mistakes"]
    if not mistakes:
        return {"total": 0, "by_subject": {}, "by_error_type": {}, "by_month": {}, "top_tags": [], "recent_trend": []}

    by_subject = dict(Counter(m.get("subject", "未知") for m in mistakes))
    by_error_type = dict(Counter(m.get("error_type", "未知") for m in mistakes))
    month_counts = Counter()
    for m in mistakes:
        try:
            month = m["created_at"][:7]
            month_counts[month] += 1
        except Exception:
            pass
    by_month = dict(sorted(month_counts.items()))
    all_tags = []
    for m in mistakes:
        all_tags.extend(m.get("tags", []))
    top_tags = [{"name": tag, "count": count} for tag, count in Counter(all_tags).most_common(10)]
    sorted_months = sorted(by_month.items())
    recent_trend = [{"month": m, "count": c} for m, c in sorted_months[-6:]]

    return {
        "total": len(mistakes),
        "by_subject": by_subject,
        "by_error_type": by_error_type,
        "by_month": by_month,
        "top_tags": top_tags,
        "recent_trend": recent_trend,
    }


def generate_profile(store):
    """生成个人认知画像"""
    mistakes = store["mistakes"]
    if not mistakes:
        return {
            "weak_subjects": [],
            "weak_error_types": [],
            "weak_tags": [],
            "summary": "暂无数据，请先使用错题问诊功能添加错题。",
            "learning_advice": [],
        }

    subject_counts = Counter(m.get("subject", "未知") for m in mistakes)
    weak_subjects = [{"name": s, "count": c, "percentage": round(c / len(mistakes) * 100, 1)} for s, c in subject_counts.most_common(5)]
    error_counts = Counter(m.get("error_type", "未知") for m in mistakes)
    weak_error_types = [{"name": e, "count": c, "percentage": round(c / len(mistakes) * 100, 1)} for e, c in error_counts.most_common(5)]
    all_tags = []
    for m in mistakes:
        all_tags.extend(m.get("tags", []))
    tag_counts = Counter(all_tags)
    weak_tags = [{"name": t, "count": c} for t, c in tag_counts.most_common(8)]

    advice = []
    top_subject = weak_subjects[0]["name"] if weak_subjects else "综合"
    top_error = weak_error_types[0]["name"] if weak_error_types else "思路不完整"
    top_tag = weak_tags[0]["name"] if weak_tags else "基础知识"

    if top_error == "概念混淆":
        advice.append(f"建议回归教材，系统梳理{top_subject}的核心概念和定理，制作思维导图对比易混概念。")
    elif top_error == "计算失误":
        advice.append(f"{top_subject}计算题建议：养成分步书写、中间结果校验的习惯，完成后用估算检验结果合理性。")
    elif top_error == "审题偏差":
        advice.append("审题训练：做题前先圈出关键词和限制条件，用一句话复述题目要求再开始解题。")
    elif top_error == "方法误用":
        advice.append(f"方法选择训练：整理{top_subject}各类题型的适用方法及特征条件，做题前先判断题型再选方法。")
    elif top_error == "逻辑跳跃":
        advice.append("逻辑训练：练习把解题步骤写得足够详细，每一步都要有明确的推导依据。")
    elif top_error == "步骤遗漏":
        advice.append("完整性训练：建立解题步骤清单，做完后逐项检查是否有遗漏的关键步骤。")

    advice.append(f"重点巩固知识点「{top_tag}」，每天做2道相关变式题，持续一周。")
    advice.append("建议每周进行一次错题复盘，对照本系统的诊断结果检查进步情况。")

    if len(mistakes) >= 5:
        recent = mistakes[:5]
        recent_subjects = [m.get("subject") for m in recent]
        if len(set(recent_subjects)) == 1:
            advice.insert(0, f"近期错题集中在{recent_subjects[0]}，建议优先攻克该学科。")

    summary = (
        f"根据{len(mistakes)}条错题记录分析，你的主要薄弱学科是「{top_subject}」，"
        f"最常见的错误类型是「{top_error}」，高频薄弱知识点是「{top_tag}」。"
    )

    return {
        "total_mistakes": len(mistakes),
        "weak_subjects": weak_subjects,
        "weak_error_types": weak_error_types,
        "weak_tags": weak_tags,
        "summary": summary,
        "learning_advice": advice,
    }


def generate_training_plan(store, mistake_id=None):
    """根据错题记录生成个性化训练计划"""
    mistakes = store["mistakes"]
    if not mistakes:
        return {"plan": [], "summary": "暂无错题数据"}

    target = None
    if mistake_id:
        target = next((m for m in mistakes if m["id"] == mistake_id), None)

    if target:
        subject = target.get("subject", "综合")
        error_type = target.get("error_type", "")
        tags = target.get("tags", [])
    else:
        subject_counts = Counter(m.get("subject", "未知") for m in mistakes)
        subject = subject_counts.most_common(1)[0][0] if subject_counts else "综合"
        error_counts = Counter(m.get("error_type", "未知") for m in mistakes)
        error_type = error_counts.most_common(1)[0][0] if error_counts else ""
        all_tags = []
        for m in mistakes:
            all_tags.extend(m.get("tags", []))
        tags = [t for t, _ in Counter(all_tags).most_common(3)]

    plan = []
    tag_str = "、".join(tags[:3]) if tags else subject

    if error_type == "概念混淆":
        plan.append({"step": 1, "action": "概念清单梳理", "detail": f"列出{tag_str}相关的所有核心概念和公式，用自己的话解释每个概念的含义和适用条件。", "duration": "20分钟"})
        plan.append({"step": 2, "action": "对比分析", "detail": "找出最容易混淆的2-3组概念，制作对比表格，标注关键区别。", "duration": "15分钟"})
    elif error_type == "计算失误":
        plan.append({"step": 1, "action": "分步计算训练", "detail": "选择3道同类题，每道题严格分步骤书写，每步做完立即检验，不允许跳步。", "duration": "25分钟"})
        plan.append({"step": 2, "action": "错因记录", "detail": "记录每道题的计算错误类型（符号/单位/运算），建立个人易错清单。", "duration": "10分钟"})
    elif error_type == "审题偏差":
        plan.append({"step": 1, "action": "审题训练", "detail": "取5道题，每题读完后先圈关键词、写已知条件和求解目标，再开始解题。", "duration": "20分钟"})
        plan.append({"step": 2, "action": "条件转换练习", "detail": "把题目条件用自己的话重新表述，检查是否有遗漏或增改。", "duration": "15分钟"})
    elif error_type == "方法误用":
        plan.append({"step": 1, "action": "方法归纳", "detail": f"整理{tag_str}的3-5种常见解题方法，标注每种方法的适用特征条件。", "duration": "20分钟"})
        plan.append({"step": 2, "action": "题型匹配练习", "detail": "做5道题，每题先判断属于哪种题型、适用哪种方法，再动笔。", "duration": "25分钟"})
    else:
        plan.append({"step": 1, "action": "错题重做", "detail": "重新做一遍原错题，不看答案，独立完成并写出完整推理过程。", "duration": "15分钟"})
        plan.append({"step": 2, "action": "变式练习", "detail": f"找2道{tag_str}的变式题，变换条件或问法，检验是否真正掌握。", "duration": "20分钟"})

    plan.append({"step": len(plan) + 1, "action": "复盘总结", "detail": "写一份简短的复盘笔记：之前错在哪、现在怎么做、学到了什么。上传到本系统归档。", "duration": "10分钟"})

    summary = f"针对「{tag_str}」方向的「{error_type}」问题，生成{len(plan)}步训练计划。"
    return {"plan": plan, "summary": summary, "focus": tag_str, "error_type": error_type}


@app.get("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.get("/<path:path>")
def static_files(path):
    return send_from_directory(FRONTEND_DIR, path)


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "model": GEMINI_MODEL, "llm_enabled": bool(GEMINI_API_KEY)})


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
    image_base64 = payload.get("image")  # base64编码的图片

    if not user_text and not image_base64:
        return jsonify({"error": "message or image is required"}), 400

    store = load_store()
    session = get_or_create_session(store, session_id)

    # 如果有图片，先去除data:前缀，直接传图片给 Gemini 做多模态分析
    if image_base64:
        if "," in image_base64:
            image_base64 = image_base64.split(",", 1)[1]

    session["messages"].append({"role": "user", "content": user_text, "created_at": now_iso()})
    if session["title"] == "新的错题问诊":
        session["title"] = build_title(user_text)

    local_answer, mistake = local_diagnosis(user_text)

    try:
        # Gemini 一站式处理：文本或图片+文本
        answer = call_gemini(user_text, session["messages"], image_base64)
        if answer is None:
            answer = local_answer
    except Exception as exc:
        answer = local_answer
        answer += f"\n\n（LLM调用失败，已切换本地诊疗模式：{exc}）"

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


@app.put("/api/mistakes/<mistake_id>")
def update_mistake(mistake_id):
    """编辑错题记录"""
    store = load_store()
    payload = request.get_json(force=True) or {}
    for item in store["mistakes"]:
        if item["id"] == mistake_id:
            if "title" in payload:
                item["title"] = payload["title"]
            if "subject" in payload:
                item["subject"] = payload["subject"]
            if "error_type" in payload:
                item["error_type"] = payload["error_type"]
            if "root_cause" in payload:
                item["root_cause"] = payload["root_cause"]
            if "correct_idea" in payload:
                item["correct_idea"] = payload["correct_idea"]
            if "tags" in payload:
                item["tags"] = payload["tags"]
            save_store(store)
            return jsonify({"ok": True, "mistake": item})
    return jsonify({"error": "not found"}), 404


@app.delete("/api/mistakes/<mistake_id>")
def delete_mistake(mistake_id):
    """删除错题记录"""
    store = load_store()
    before = len(store["mistakes"])
    store["mistakes"] = [m for m in store["mistakes"] if m["id"] != mistake_id]
    save_store(store)
    return jsonify({"deleted": before - len(store["mistakes"])})


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


@app.get("/api/statistics")
def statistics():
    """获取错题统计数据"""
    store = load_store()
    stats = generate_statistics(store)
    return jsonify(stats)


@app.get("/api/profile")
def profile():
    """获取个人认知画像"""
    store = load_store()
    prof = generate_profile(store)
    return jsonify(prof)


@app.get("/api/training/<mistake_id>")
def training_plan(mistake_id):
    """获取针对特定错题的训练计划"""
    store = load_store()
    plan = generate_training_plan(store, mistake_id)
    return jsonify(plan)


@app.get("/api/training")
def training_plan_overall():
    """获取整体训练计划"""
    store = load_store()
    plan = generate_training_plan(store)
    return jsonify(plan)


@app.post("/api/ocr")
def ocr_image():
    """单独的OCR接口"""
    payload = request.get_json(force=True) or {}
    image_base64 = payload.get("image", "")
    if not image_base64:
        return jsonify({"error": "image is required"}), 400

    if "," in image_base64:
        image_base64 = image_base64.split(",", 1)[1]

    try:
        text = call_vision_ocr(image_base64)
        return jsonify({"text": text})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    ensure_store()
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG") == "1",
        use_reloader=False,
    )
