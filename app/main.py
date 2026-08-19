"""本地 AI 工作台 —— Web 应用入口。"""
import os
import time

from flask import Flask, jsonify, request, send_file

from .config import load_settings
from .embeddings import get_embedder
from .llm import get_llm
from .logger import LogStore
from .rag import Index
from . import tools as tool_mod
from .auth import Auth

settings = load_settings()
# 统一转绝对路径：避免 Flask send_file 相对路径解析到 app/ 目录的坑
settings.data_dir = os.path.abspath(settings.data_dir)
settings.upload_dir = os.path.abspath(settings.upload_dir)
os.makedirs(settings.data_dir, exist_ok=True)
os.makedirs(settings.upload_dir, exist_ok=True)

embedder = get_embedder(settings)
index = Index(
    os.path.join(settings.data_dir, "index.json"),
    embedder=embedder,
    threshold=settings.retrieve_threshold,
    lexical_threshold=settings.retrieve_lexical_threshold,
    dedup_threshold=settings.dedup_threshold,
)
logs = LogStore(
    os.path.join(settings.data_dir, "logs.jsonl"),
    max_mb=settings.log_max_mb,
)
llm = get_llm(settings)
auth = Auth(settings, logs)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 单文件最大 20MB
_STATIC = os.path.join(os.path.dirname(__file__), "static")

SYSTEM_PROMPT = (
    "你是一个部署在客户本地、保护隐私的 AI 助手，请始终用中文回答。"
    "当用户提供参考资料时，优先依据参考资料回答；"
    "如果参考资料不足以回答，请明确说明。回答末尾列出引用的文档名。"
)


def _cost(tokens_in: int, tokens_out: int) -> float:
    return tokens_in / 1e6 * settings.price_in + tokens_out / 1e6 * settings.price_out


# ---------------- 访问认证 ----------------

_AUTH_EXEMPT_PREFIXES = ("/api/auth",)


def _get_session_token():
    return request.cookies.get("session") or request.headers.get("X-Session", "")


@app.before_request
def require_auth():
    """除登录接口与首页外，全部接口要求有效会话；总开关关闭时全部拒绝。"""
    if request.path == "/" or request.path.startswith(_AUTH_EXEMPT_PREFIXES):
        return None
    if request.path.startswith("/api/health"):
        return None
    if not auth.access_enabled():
        return jsonify(error="演示已关闭，请联系管理员"), 403
    if auth.auth_enabled() and not auth.check_session(_get_session_token()):
        return jsonify(error="未登录或会话已过期"), 401


@app.post("/api/auth/request")
def auth_request():
    result = auth.request_otp()
    return jsonify(result)


@app.post("/api/auth/login")
def auth_login():
    body = request.get_json(silent=True) or {}
    code = body.get("code") or ""
    ok, err = auth.verify_otp(code)
    if not ok:
        return jsonify(error=err), 401
    token = auth.create_session()
    resp = jsonify(ok=True)
    resp.set_cookie(
        "session", token,
        httponly=True, max_age=settings.session_ttl_seconds, samesite="Lax",
    )
    return resp


@app.get("/api/auth/check")
def auth_check():
    trial = auth.trial_seconds()
    return jsonify(
        ok=auth.check_session(_get_session_token()),
        auth_enabled=auth.auth_enabled(),
        access_enabled=auth.access_enabled(),
        trial_minutes=int(trial / 60) if trial else 0,
    )


@app.post("/api/auth/logout")
def auth_logout():
    auth.destroy_session(_get_session_token())
    resp = jsonify(ok=True)
    resp.delete_cookie("session")
    return resp


@app.get("/")
def home():
    return send_file(os.path.join(_STATIC, "index.html"))


@app.get("/api/health")
def health():
    return jsonify(status="ok", provider=llm.name, model=getattr(llm, "model", "-"))


@app.get("/api/config")
def config():
    return jsonify(
        provider=llm.name,
        model=getattr(llm, "model", "-"),
        retrieval=embedder.name,
        image_provider=settings.image_provider,
        docs=len(index.list()),
    )


@app.post("/api/chat")
def chat():
    body = request.get_json(silent=True) or {}
    msg = (body.get("message") or "").strip()
    if not msg:
        logs.add(type="chat_request", level="error", message="", error="消息不能为空")
        return jsonify(error="消息不能为空"), 400
    use_kb = body.get("use_kb", True)

    start = time.time()
    ret = index.retrieve(msg, settings.top_k) if use_kb else {"hits": [], "removed": 0}
    context = ret["hits"]
    logs.add(
        type="retrieval",
        message=msg[:60],
        hits=len(context),
        removed=ret["removed"],
        mode=embedder.name,
        top_score=round(context[0]["score"], 4) if context else 0,
    )

    user_prompt = msg
    if context:
        blocks = "\n\n".join(
            f"【来自文档《{c['doc']}》{('· ' + c['heading']) if c.get('heading') else ''}】\n{c['text']}"
            for c in context
        )
        user_prompt = f"参考资料：\n{blocks}\n\n问题：{msg}"

    try:
        answer, tokens_in, tokens_out = llm.chat(
            [{"role": "user", "content": user_prompt}], system=SYSTEM_PROMPT
        )
    except Exception as e:
        logs.add(type="chat_request", level="error", message=msg[:60], error=str(e)[:300])
        return jsonify(error=f"模型调用失败: {e}"), 502

    duration = (time.time() - start) * 1000
    logs.add(
        type="chat_request",
        message=msg[:60],
        hits=len(context),
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost=round(_cost(tokens_in, tokens_out), 6),
        duration_ms=round(duration, 1),
        model=getattr(llm, "model", llm.name),
    )
    return jsonify(answer=answer, sources=context)


@app.post("/api/documents")
def upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify(error="未选择文件"), 400
    name = os.path.basename(f.filename)
    raw = f.read()
    ext = name.lower().rsplit(".", 1)[-1] if "." in name else ""
    if ext in ("docx", "pdf"):
        text = _extract_doc_text(ext, raw)
        if not text:
            return jsonify(error="无法从文件中提取文字（可能是扫描件/图片型 PDF）"), 400
    elif ext == "xlsx":
        try:
            text = _extract_xlsx_text(raw)
        except Exception as e:
            return jsonify(error=f"Excel 解析失败: {e}"), 400
        if not text.strip():
            return jsonify(error="Excel 中没有可读内容"), 400
    else:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = raw.decode("gbk")
            except UnicodeDecodeError:
                return jsonify(error="仅支持文本(.txt/.md/.csv/.json/.log)、Word(.docx)、PDF(.pdf)、Excel(.xlsx)"), 400
    text = text.lstrip("\ufeff")  # 去掉 Windows 常见 BOM 头

    dest = os.path.join(settings.upload_dir, name)
    with open(dest, "wb") as fp:
        fp.write(raw)

    doc = index.add_document(name, dest, text, settings.chunk_size, settings.chunk_min_size)
    logs.add(type="upload", name=name, chunks=len(doc["chunks"]), mode=embedder.name)
    return jsonify(id=doc["id"], name=doc["name"], chunks=len(doc["chunks"]))


def _extract_doc_text(ext: str, raw: bytes) -> str:
    """从 Word/PDF 提取文字（docx 解析段落，pdf 逐页提取）。"""
    try:
        import io
        if ext == "docx":
            from docx import Document
            doc = Document(io.BytesIO(raw))
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:
        return ""


def _extract_xlsx_text(raw: bytes, max_rows_per_sheet: int = 1000) -> str:
    """把 Excel 的【全部工作表】转成文本：工作表名作为标题，单元格用 | 分隔。

    例：
    # 工作表：中文目录
    商品名称 | 价格 | 描述
    夏季连衣裙 | 199 | 轻薄透气
    """
    import io
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    parts = []
    for ws in wb.worksheets:
        parts.append(f"# 工作表：{ws.title}")
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i >= max_rows_per_sheet:
                parts.append("...(该表行数过多，已截断)")
                break
            cells = ["" if c is None else str(c).strip() for c in row]
            parts.append(" | ".join(cells).rstrip(" |") + "；")  # 行尾加分号，避免切片时行粘连
    wb.close()
    return "\n".join(p for p in parts if p.strip())


@app.get("/api/documents")
def documents():
    return jsonify(documents=index.list())


@app.get("/api/documents/<doc_id>")
def document_detail(doc_id: str):
    """查看单篇文档的切片详情（自检用）。"""
    info = index.detail(doc_id)
    if info is None:
        return jsonify(error="文档不存在"), 404
    return jsonify(info)


@app.post("/api/documents/reindex")
def reindex_documents():
    """按当前 .env 切片参数重新切片全部文档（从原件重读）。"""
    n = index.reindex(settings.chunk_size, settings.chunk_min_size)
    logs.add(type="system", message=f"重新切片完成: {n} 篇")
    return jsonify(ok=True, docs=n)


@app.delete("/api/documents/<doc_id>")
def delete_document(doc_id: str):
    doc = next((d for d in index.docs if d["id"] == doc_id), None)
    if not index.remove(doc_id):
        return jsonify(error="文档不存在"), 404
    logs.add(type="delete", name=(doc or {}).get("name", doc_id))
    return jsonify(ok=True)


# ---------------- 运行监控 ----------------

@app.get("/api/logs")
def api_logs():
    limit = min(int(request.args.get("limit", 100)), 500)
    ftype = request.args.get("type") or None
    return jsonify(logs=logs.recent(limit, ftype))


@app.get("/api/stats")
def api_stats():
    return jsonify(logs.stats(settings.price_in, settings.price_out))


@app.post("/api/logs/clear")
def api_logs_clear():
    logs.clear()
    logs.add(type="system", message="日志已清空")
    return jsonify(ok=True)


# ---------------- 工具中心 ----------------

@app.post("/api/tools/text/batch")
def tool_text_batch():
    body = request.get_json(silent=True) or {}
    items = body.get("items") or []
    if not items:
        return jsonify(error="没有输入内容"), 400
    if len(items) > 200:
        return jsonify(error="单次最多 200 条"), 400
    results = tool_mod.batch_text(
        items,
        body.get("mode", "rewrite"),
        body.get("language", "英文"),
        body.get("instruction", ""),
        llm, logs, settings,
        concurrency=settings.tool_concurrency,
    )
    return jsonify(results=results)


@app.post("/api/tools/image/generate")
def tool_image_generate():
    body = request.get_json(silent=True) or {}
    prompts = body.get("prompts") or []
    if not prompts:
        return jsonify(error="没有输入提示词"), 400
    if len(prompts) > 20:
        return jsonify(error="单次最多 20 张"), 400
    images = tool_mod.batch_images(prompts, body.get("size", "512x512"), settings, logs)
    return jsonify(images=images, provider=settings.image_provider)


@app.get("/api/tools/image/<name>")
def tool_image_get(name: str):
    return send_file(os.path.join(settings.data_dir, "output", name), mimetype="image/png")


@app.post("/api/tools/table/preview")
def tool_table_preview():
    f = request.files.get("file")
    if not f:
        return jsonify(error="未选择文件"), 400
    try:
        info = tool_mod.preview_table(os.path.basename(f.filename or ""), f.read())
    except ValueError as e:
        return jsonify(error=str(e)), 400
    return jsonify(info)


@app.post("/api/tools/table/process")
def tool_table_process():
    f = request.files.get("file")
    if not f:
        return jsonify(error="未选择文件"), 400
    name = os.path.basename(f.filename or "")
    raw = f.read()
    cols_raw = (request.form.get("columns") or request.form.get("column") or "").strip()
    columns = [c.strip() for c in cols_raw.split(",") if c.strip()]
    if not columns:
        return jsonify(error="未选择要处理的列"), 400
    mode = request.form.get("mode", "rewrite") or "rewrite"
    language = request.form.get("language", "英文") or "英文"
    instruction = request.form.get("instruction", "") or ""
    try:
        out_path, out_rows = tool_mod.process_table(
            name, raw, columns, mode, language, instruction, llm, logs, settings
        )
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:
        return jsonify(error=f"处理失败: {e}"), 500
    return jsonify(
        download="/api/tools/download/" + os.path.basename(out_path),
        rows=len(out_rows) - 1,
        preview=out_rows[:5],
    )


@app.get("/api/tools/download/<name>")
def tool_download(name: str):
    return send_file(os.path.join(settings.data_dir, "output", name), as_attachment=True)


if __name__ == "__main__":
    app.run(host=settings.host, port=settings.port, threaded=True)
