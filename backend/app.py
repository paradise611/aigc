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

ZHIPU_API_KEY = os.getenv("ZHIPU_API_KEY", "")
ZHIPU_TEXT_MODEL = os.getenv("ZHIPU_TEXT_MODEL", "glm-4-flash")
ZHIPU_VISION_MODEL = os.getenv("ZHIPU_VISION_MODEL", "glm-4v-flash")

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
    with DATA_FILE.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def save_store(store):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with DATA_FILE.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)


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
    if any(token in text for token in ["函数", "方程", "导数", "几何", "概率", "矩阵", "数列", "不等式", "三角", "对数", "指数", "积分", "微分", "极限", "向量", "坐标", "圆", "面积", "体积", "勾股", "相似", "全等"]) or re.search(r"\d+\s*[+\-*/=]", text):
        return "数学"
    if any(token in text for token in ["英语", "完形", "阅读", "语法", "单词", "翻译", "作文", "听力", "时态", "语态", "从句", "词汇"]):
        return "英语"
    if any(token in text for token in ["力", "电路", "速度", "加速度", "压强", "牛顿", "电流", "电压", "电阻", "磁场", "功", "能", "功率", "浮力", "密度", "光", "波", "热"]):
        return "物理"
    if any(token in text for token in ["化学", "反应", "离子", "方程式", "溶液", "元素", "分子", "原子", "酸碱", "氧化", "还原", "沉淀", "气体"]):
        return "化学"
    if any(token in text for token in ["生物", "细胞", "遗传", "基因", "光合", "呼吸", "酶", "DNA", "RNA", "蛋白质", "生态"]):
        return "生物"
    if any(token in text for token in ["语文", "古诗", "文言文", "作文", "阅读理解", "修辞", "描写", "论证", "作者"]):
        return "语文"
    if any(token in lower for token in ["python", "java", "算法", "代码", "递归", "循环", "数组", "排序", "编程"]):
        return "计算机"
    return "综合"


def infer_error_type(text):
    mapping = [
        ("概念混淆", ["概念", "定义", "性质", "公式", "定理", "混淆", "搞混", "记错", "不知道", "不理解", "没学过"]),
        ("审题偏差", ["题意", "条件", "没看清", "问什么", "范围", "漏看", "看错", "忽略了", "没注意到", "审题"]),
        ("步骤遗漏", ["漏", "少写", "跳步", "步骤", "过程", "不完整", "缺少", "没写全"]),
        ("计算失误", ["算错", "计算", "符号", "小数", "单位", "粗心", "加错", "减错", "乘错", "除错", "代错"]),
        ("方法误用", ["方法", "套公式", "模型", "思路", "选错", "用错", "不合适", "不适用", "解法"]),
        ("逻辑跳跃", ["推不出", "为什么", "逻辑", "所以", "推理", "因果", "跳跃", "矛盾"]),
    ]
    for error_type, keys in mapping:
        if any(key in text for key in keys):
            return error_type
    return "思路不完整"


def extract_tags(text):
    candidates = ["函数", "方程", "几何", "概率", "导数", "积分", "数列", "三角", "向量", "不等式",
                  "阅读理解", "语法", "时态", "从句", "作文", "文言文",
                  "力学", "电路", "磁场", "光学", "热学", "运动", "能量",
                  "化学方程式", "氧化还原", "酸碱", "有机", "无机",
                  "遗传", "细胞", "生态", "代谢",
                  "算法", "数据结构", "递归", "循环"]
    tags = [tag for tag in candidates if tag in text]
    if not tags:
        tags = [infer_subject(text), infer_error_type(text)]
    return list(dict.fromkeys(tags))[:4]


def local_diagnosis(user_text, has_image=False):
    subject = infer_subject(user_text)
    error_type = infer_error_type(user_text)
    tags = extract_tags(user_text)
    focus = "、".join(tags) if tags else "综合"

    lower = user_text.strip().lower()

    # ====== 1. 问候 / 闲聊 ======
    greetings = ["你好", "hi", "hello", "嗨", "在吗", "在不在", "早上好", "下午好", "晚上好"]
    if any(g in lower for g in greetings) or (len(user_text) <= 5 and not has_image):
        answer = (
            '\U0001f44b 赛博错题医生 24 小时在线为您服务！\n\n'
            '您好！很高兴能帮助您诊断学习中的\u201c小毛病\u201d \U0001fa7a\n\n'
            '请把您遇到的题目、您尝试的解题过程或者任何困惑告诉我吧！\n'
            '我是您的 AI 认知教练，会像一位耐心又专业的医生一样，\n'
            '引导您找到问题根源，修复认知偏差，让您下次遇到类似问题时，\n'
            '能够充满自信地独立解决！\U0001f4aa\n\n'
            '期待您的提问哦！\u2728'
        )
        return answer, _make_mistake(user_text, subject, error_type, tags, focus)

    # ====== 2. 感谢 / 告别 ======
    thanks = ["谢谢", "感谢", "多谢", "辛苦了", "拜拜", "再见", "bye"]
    if any(t in lower for t in thanks):
        answer = "😊 不客气！随时欢迎回来继续问诊。学习路上，我一直都在。加油！💪"
        return answer, _make_mistake(user_text, subject, error_type, tags, focus)

    # ====== 3. 图片上传（带或不带文字描述） ======
    if has_image:
        answer = "📷 正在识别图片..."
        return answer, _make_mistake(user_text, subject, error_type, tags, focus)

    # ====== 4. 询问功能 / 自述 ======
    ask_self = ["你是谁", "你能做什么", "功能", "怎么用", "帮助"]
    if any(a in lower for a in ask_self):
        answer = (
            "🤖 我是赛博错题医生，你的 AI 认知教练！\n\n"
            "我能帮你：\n"
            "🔍 诊断错题 — 分析你的解题过程，定位错误节点\n"
            "🧠 根因分析 — 判断是概念混淆、审题偏差还是计算失误\n"
            "💬 追问引导 — 用苏格拉底式提问帮你自己发现错误\n"
            "✅ 正确思路 — 给出清晰的分步解答\n"
            "📚 巩固建议 — 推荐同类变式题策略\n\n"
            "👉 直接发一道错题过来试试吧！"
        )
        return answer, _make_mistake(user_text, subject, error_type, tags, focus)

    # ====== 5. 真正的错题诊断 ======
    has_question_indicators = any(
        k in user_text
        for k in ["题", "问", "怎么做", "为什么", "哪里错", "求", "计算", "证明", "解", "答案", "步骤"]
    )

    if has_question_indicators or len(user_text) > 30:
        answer = (
            f"🔍 初步诊断：这道题属于 **{subject}** 方向，\n"
            f"从你的描述来看，可能的错误类型是「{error_type}」。\n\n"
            f"咱们按这个思路来复盘：\n"
            f"1. 先确认题目到底问什么，圈出已知条件和求解目标\n"
            f"2. 回想你当时是怎么一步步做的，找出第一处犹豫的地方\n"
            f"3. 判断那个犹豫是因为：搞混了概念？看漏了条件？还是方法没选对？\n"
            f"4. 然后重新走一遍正确思路，用变式题验证是否真懂了\n\n"
            f"💡 如果你把原始作答过程补上来，我可以精准定位到具体错误节点。\n"
            f"你不妨先说说：你当时是从哪个条件开始觉得不对劲的？"
        )
    else:
        # ====== 6. 简短消息 / 不确定意图 ======
        answer = (
            f"😊 你好！看起来你想和我聊点什么？\n\n"
            f"我主要擅长的是 **错题诊断**——你可以：\n"
            f"📝 直接发一道错题\n"
            f"📝 贴上你的原始解答过程\n"
            f"📝 告诉我你困惑的地方\n\n"
            f"我会帮你定位错误、分析根因、给出正确思路和巩固建议！\n"
            f"请随便发一道题来试试吧～"
        )

    return answer, _make_mistake(user_text, subject, error_type, tags, focus)


def _make_mistake(user_text, subject, error_type, tags, focus):
    """构建错题记录"""
    # Heuristic mastery level based on user's actual question signals
    lower = user_text.lower()
    base = 50

    # Positive signals: user shows their own work / reasoning
    if any(k in user_text for k in ["我算", "我写", "我得", "我做", "我求", "答", "解", "步骤", "过程"]):
        base += 15
    # User is verifying (shows some confidence)
    if any(k in lower for k in ["对吗", "是不是", "对不对", "验证", "检查"]):
        base += 8
    # User asks for deeper understanding (engaged but confused)
    if any(k in lower for k in ["为什么", "怎么做", "怎么求", "怎么算", "不理解"]):
        base -= 8
    # User expresses pure confusion / helplessness
    if any(k in lower for k in ["不会", "不懂", "不明白", "不知道", "搞混", "总是", "经常"]):
        base -= 12

    # Error-type based adjustment
    type_mod = {
        "概念混淆": -15,
        "逻辑跳跃": -8,
        "审题偏差": -3,
        "步骤遗漏": +2,
        "计算失误": +10,
        "方法误用": -5,
        "思路不完整": -5,
    }
    base += type_mod.get(error_type, 0)

    # Question length indicates detail level
    if len(user_text) < 15:
        base -= 5
    elif len(user_text) > 60:
        base += 5

    # Small variance based on text (deterministic but feels varied)
    import hashlib
    h = int(hashlib.md5(user_text.encode()).hexdigest()[:4], 16)
    base += (h % 11) - 5  # ±5 jitter

    level = max(15, min(95, base))
    return {
        "id": uuid.uuid4().hex,
        "title": build_title(user_text),
        "subject": subject,
        "error_type": error_type,
        "level": level,
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


def build_title(text):
    cleaned = re.sub(r"\s+", " ", text).strip()
    cleaned = re.sub(r"[#*_`>]+", "", cleaned)
    return (cleaned[:22] + "...") if len(cleaned) > 24 else cleaned or "未命名错题"


def call_gemini(user_text, history, image_base64=None, image_mime="image/png"):
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
            {"inline_data": {"mime_type": image_mime, "data": image_base64}},
        ]
    else:
        parts = [{"text": user_text}]
    contents.append({"role": "user", "parts": parts})

    body = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
    }

    timeout = 30 if image_base64 else 10

    try:
        resp = requests.post(url, json=body, timeout=timeout)
        data = resp.json()

        if "candidates" in data and len(data["candidates"]) > 0:
            candidate = data["candidates"][0]
            if "content" in candidate and "parts" in candidate["content"]:
                return candidate["content"]["parts"][0].get("text", None)

        # 记录 API 错误
        if "error" in data:
            print(f"[Gemini] API错误: {data['error']}")
    except requests.exceptions.Timeout:
        print("[Gemini] 请求超时，回退本地诊疗模式")
    except requests.exceptions.ConnectionError:
        print("[Gemini] 网络无法连接，回退本地诊疗模式")
    except Exception as exc:
        print(f"[Gemini] 调用异常: {exc}")
    return None


def call_zhipu(user_text, history, image_base64=None, image_mime="image/png"):
    """调用智谱 API 进行诊断（支持文本和图片）"""
    if not ZHIPU_API_KEY:
        return None

    url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"

    system_prompt = (
        '你是"赛博错题医生"，一个面向学生的AI认知教练。你的核心任务不是直接给答案，而是：\n\n'
        '诊疗流程：\n'
        '1. 初步诊断：快速判断题目学科、知识点和难度\n'
        '2. 错误定位：如果用户提供了作答过程，精准定位第一处错误节点\n'
        '3. 根因分析：区分错误类型\u2014\u2014概念混淆/审题偏差/步骤遗漏/逻辑跳跃/计算失误/方法误用\n'
        '4. 苏格拉底式追问：不要直接说「你错了」，而是用提问引导反思\n'
        '5. 认知修复：给出正确思路，但要强调理解而非记忆\n'
        '6. 巩固建议：推荐同类变式题的解题策略\n\n'
        '输出时请使用纯文本格式，不要使用Markdown语法（不要用 ###、**、* 等符号），也不要用LaTeX数学公式（不要用 \\( \\) \\[ \\] \\frac \\int \\sum 等）。\n'
        '数学表达式请用普通文字描述，如"积分 x·cosx dx"、"x的平方"等。\n'
        '用emoji和自然换行来组织内容结构。示例：\n'
        '\U0001f50d 初步诊断：学科/知识点/难度\n'
        '\u274c 错误定位：第几步出了问题\n'
        '\U0001f9e0 根因分析：为什么出错（认知层面）\n'
        '\U0001f4ac 追问引导：1-2个引导学生反思的问题\n'
        '\u2705 正确思路：清晰的分步解答\n'
        '\U0001f4da 巩固建议：同类题策略 + 知识点梳理\n\n'
        '核心原则：\n'
        '- 永远保持鼓励和耐心，像一位好老师\n'
        '- 引导学生自己发现错误，而非直接指出\n'
        '- 关注思维过程，而非仅仅答案对错\n'
        '- 用通俗语言解释复杂概念'
    )

    messages = [{"role": "system", "content": system_prompt}]

    for item in history[-8:]:
        role = "assistant" if item["role"] == "assistant" else "user"
        messages.append({"role": role, "content": item["content"]})

    if image_base64:
        model = ZHIPU_VISION_MODEL
        user_content = [
            {"type": "text", "text": user_text or "请识别这张图片中的题目，并进行分析。"},
            {"type": "image_url", "image_url": {"url": f"data:{image_mime};base64,{image_base64}"}},
        ]
    else:
        model = ZHIPU_TEXT_MODEL
        user_content = user_text

    messages.append({"role": "user", "content": user_content})

    body = {
        "model": model,
        "messages": messages,
        "stream": False,
    }

    headers = {
        "Authorization": f"Bearer {ZHIPU_API_KEY}",
        "Content-Type": "application/json",
    }

    timeout = 60 if image_base64 else 30

    try:
        resp = requests.post(url, json=body, headers=headers, timeout=timeout)
        data = resp.json()

        if "choices" in data and len(data["choices"]) > 0:
            return data["choices"][0]["message"]["content"]

        if "error" in data:
            print(f"[智谱] API错误: {data['error']}")
    except requests.exceptions.Timeout:
        print("[智谱] 请求超时")
    except requests.exceptions.ConnectionError:
        print("[智谱] 网络无法连接")
    except Exception as exc:
        print(f"[智谱] 调用异常: {exc}")

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
    return jsonify({
        "ok": True,
        "model": f"{ZHIPU_TEXT_MODEL} / {ZHIPU_VISION_MODEL}",
        "llm_enabled": bool(ZHIPU_API_KEY),
    })


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

    # 如果有图片，先去除data:前缀，提取MIME类型
    image_mime = None
    if image_base64:
        if "," in image_base64:
            # "data:image/png;base64,xxxx" → mime="image/png", data="xxxx"
            header, data = image_base64.split(",", 1)
            image_base64 = data
            if ":" in header and ";" in header:
                image_mime = header.split(":", 1)[1].split(";", 1)[0]
        if not image_mime:
            image_mime = "image/png"

    session["messages"].append({"role": "user", "content": user_text, "created_at": now_iso()})
    if session["title"] == "新的错题问诊":
        session["title"] = build_title(user_text)

    local_answer, mistake = local_diagnosis(user_text, has_image=bool(image_base64))

    try:
        answer = call_zhipu(user_text, session["messages"], image_base64, image_mime)
        if answer is None:
            if image_base64:
                answer = (
                    "📷 图片已收到，但 AI 服务当前不可用。\n\n"
                    "请把题目内容用文字发给我，我会帮你诊断！\n"
                    "比如：这道题是什么学科？题目问什么？你卡在哪一步？"
                )
            else:
                answer = local_answer
    except Exception:
        answer = local_answer

    # 用 AI 回复内容 + 用户问题重新推断错题元数据，让分析页更精准
    combined = user_text + " " + (answer or "")
    if answer and answer != local_answer:
        mistake["subject"] = infer_subject(combined)
        mistake["error_type"] = infer_error_type(combined)
        mistake["tags"] = extract_tags(combined)

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
