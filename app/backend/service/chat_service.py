import json
from collections import OrderedDict

from fastapi import Request
from fastapi.responses import StreamingResponse
from langchain_chroma import Chroma
from langchain_community.embeddings import DashScopeEmbeddings
from openai import OpenAI

from app.backend.config import settings
from app.backend.logger import logger

CLIENT = OpenAI(
    api_key=settings.openai_api_key,
    base_url=settings.openai_base_url,
)

# ============ 对话记忆 ============
# 内存级存储：thread_id → [{"role": "user"/"assistant", "content": "..."}]
# 每轮对话 2 条消息（user + assistant），保留最近 10 轮
MAX_HISTORY_TURNS = 10
_conversations: dict[str, list[dict]] = {}


def _get_history(thread_id: str) -> list[dict]:
    """获取指定会话的历史消息。"""
    return _conversations.get(thread_id, [])


def _save_turn(thread_id: str, question: str, answer: str):
    """将一轮对话追加到历史，超限自动裁剪旧消息。"""
    if not thread_id:
        return
    if thread_id not in _conversations:
        _conversations[thread_id] = []
    history = _conversations[thread_id]
    history.append({"role": "user", "content": question})
    history.append({"role": "assistant", "content": answer})
    # 裁剪：保留最近 MAX_HISTORY_TURNS 轮（每轮 2 条）
    max_msgs = MAX_HISTORY_TURNS * 2
    if len(history) > max_msgs:
        _conversations[thread_id] = history[-max_msgs:]


def _get_vector_store():
    return Chroma(
        persist_directory=settings.chroma_path,
        embedding_function=DashScopeEmbeddings(
            dashscope_api_key=settings.openai_api_key,
            model=settings.embedding_model,
        ),
        collection_name=settings.chroma_collection_name,
    )


def _build_messages(question: str, context: str, history: list[dict] | None = None) -> list[dict]:
    system = settings.system_prompt
    if context.strip():
        system += (
            "\n\n以下是知识库中检索到的参考资料，可能对回答有帮助。"
            "请结合这些资料和你自己的专业知识，给出完整的回答。"
            "即使资料中没涉及的内容，也请补充。\n\n参考资料：\n" + context
        )
    messages = [{"role": "system", "content": system}]
    # 插入历史对话，让模型理解上下文（追问、指代消解）
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": question})
    return messages


def _retrieve_context(question: str):
    """从 Chroma 检索与问题相关的文本片段，返回 (context_string, sources_list)。"""
    try:
        vector_store = _get_vector_store()
        results = vector_store.similarity_search_with_score(question, k=settings.top_k)

        context_parts = []
        # 用 OrderedDict 去重并保留来源顺序
        sources = OrderedDict()
        for doc, distance in results:
            # Chroma 返回的是 cosine distance；转换成相似度（0~1）便于阈值比较和前端展示
            similarity = max(0.0, 1.0 - float(distance))
            if similarity < settings.score_threshold:
                continue
            context_parts.append(doc.page_content)
            source = doc.metadata.get("source", "未知文档")
            sources[source] = {"source": source, "score": round(similarity, 4)}

        return "\n\n---\n\n".join(context_parts), list(sources.values())
    except Exception as e:
        logger.error(f"检索失败：{e}")
        return "", []


def _stream_chat(question: str, thread_id: str = "", request: Request | None = None):
    """SSE 流式对话，带 RAG 检索增强 + 多轮对话记忆。"""
    history = _get_history(thread_id) if thread_id else []
    context, sources = _retrieve_context(question)
    messages = _build_messages(question, context, history)

    if history:
        logger.info(f"携带 {len(history)} 条历史消息，thread_id={thread_id}")

    completion = CLIENT.chat.completions.create(
        model=settings.openai_model_name,
        messages=messages,
        stream=True,
        stream_options={"include_usage": True},
    )
    answer_parts = []

    async def event_stream():
        completed = False
        try:
            for chunk in completion:
                if request and await request.is_disconnected():
                    logger.info(f"客户端已断开连接，停止流式输出，thread_id={thread_id}")
                    break
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content
                if not delta:
                    continue
                answer_parts.append(delta)
                yield f"data: {json.dumps({'content': delta}, ensure_ascii=False)}\n\n"

            else:
                completed = True

            full_answer = "".join(answer_parts)
            if completed:
                logger.info(f"模型输出：{full_answer}")
                _save_turn(thread_id, question, full_answer)

                if sources:
                    yield f"data: {json.dumps({'sources': sources}, ensure_ascii=False)}\n\n"

                yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error(f"streaming error: {e}")
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream; charset=utf-8")
