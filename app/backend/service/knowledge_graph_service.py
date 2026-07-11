import json
import re
from pathlib import Path

from app.backend.config import settings
from app.backend.db.models import GraphEntity, GraphRelation
from app.backend.db.session import SessionLocal
from app.backend.logger import logger
from app.backend.service.chat_service import CLIENT

KG_EXTRACTION_PROMPT = """你是一个网络安全知识图谱构建专家。从以下文档中提取安全实体和关系。

## 实体类型（只能从以下选）
{labels}

## 关系类型（只能从以下选）
{relations}

## 输出格式
严格输出 JSON 数组，每个元素包含:
- subject: 源实体名称
- subject_type: 源实体类型（必须是上面列出的类型之一）
- relation: 关系类型（必须是上面列出的类型之一）
- object: 目标实体名称
- object_type: 目标实体类型（必须是上面列出的类型之一）

仅输出 JSON 数组，不要任何解释，不要 markdown 代码块标记。

## 文档内容
{content}"""


def _clean_json(text: str) -> str:
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    text = re.sub(r"\s*```$", "", text.strip())
    return text


def _chunk_text(text: str, size: int = 2000) -> list[str]:
    return [text[i:i + size] for i in range(0, len(text), size)]


def _load_text(file_path: str, mime_type: str | None) -> str:
    path = Path(file_path)
    ext = path.suffix.lower()
    if ext == ".pdf":
        try:
            from langchain_community.document_loaders import PyPDFLoader
            loader = PyPDFLoader(file_path)
            pages = loader.load()
            return "\n".join(p.page_content for p in pages)
        except Exception:
            return ""
    else:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""


class KnowledgeGraphService:

    def _parse_labels(self, raw: str) -> list[str]:
        try:
            return json.loads(raw)
        except Exception:
            return ["漏洞", "攻击手法", "安全工具", "网络协议", "防御措施", "合规标准", "威胁组织"]

    def _parse_relations(self, raw: str) -> list[str]:
        try:
            return json.loads(raw)
        except Exception:
            return ["利用", "缓解", "依赖", "属于", "检测", "变种", "参考", "影响"]

    def extract_entities(self, doc_id: int, file_path: str, mime_type: str | None,
                         original_filename: str = "") -> bool:
        labels = self._parse_labels(settings.kg_entity_labels)
        relations = self._parse_labels(settings.kg_relation_types)

        text = _load_text(file_path, mime_type)
        if not text.strip():
            logger.warning(f"图谱抽取：文档内容为空 doc={doc_id}")
            return False

        chunks = _chunk_text(text, settings.kg_chunk_size)
        all_triples = []

        for i, chunk in enumerate(chunks):
            prompt = KG_EXTRACTION_PROMPT.format(
                labels=", ".join(labels),
                relations=", ".join(relations),
                content=chunk,
            )
            try:
                resp = CLIENT.chat.completions.create(
                    model=settings.openai_model_name,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    max_tokens=4096,
                )
                raw = resp.choices[0].message.content or ""
                raw = _clean_json(raw)
                triples = json.loads(raw)
                if isinstance(triples, list):
                    all_triples.extend(triples)
            except json.JSONDecodeError:
                logger.warning(f"图谱抽取：第 {i + 1} 段 JSON 解析失败，重试中...")
                try:
                    resp2 = CLIENT.chat.completions.create(
                        model=settings.openai_model_name,
                        messages=[
                            {"role": "user", "content": prompt},
                            {"role": "assistant", "content": raw},
                            {"role": "user", "content": "请重新输出纯 JSON 数组，不要 markdown 代码块。"},
                        ],
                        temperature=0.1,
                        max_tokens=4096,
                    )
                    raw2 = resp2.choices[0].message.content or ""
                    raw2 = _clean_json(raw2)
                    triples = json.loads(raw2)
                    if isinstance(triples, list):
                        all_triples.extend(triples)
                except Exception:
                    logger.error(f"图谱抽取：第 {i + 1} 段重试仍然失败，跳过")
            except Exception as e:
                logger.error(f"图谱抽取：第 {i + 1} 段 LLM 调用失败: {e}")

        if not all_triples:
            logger.info(f"图谱抽取：文档未抽到实体 doc={doc_id}")
            return False

        if len(all_triples) > settings.kg_max_entities_per_doc:
            logger.info(f"图谱抽取：实体数超限 {len(all_triples)} > {settings.kg_max_entities_per_doc}，截断")
            all_triples = all_triples[:settings.kg_max_entities_per_doc]

        db = SessionLocal()
        try:
            for t in all_triples:
                subject = str(t.get("subject", "")).strip()
                subject_type = str(t.get("subject_type", "")).strip()
                relation = str(t.get("relation", "")).strip()
                obj = str(t.get("object", "")).strip()
                obj_type = str(t.get("object_type", "")).strip()
                if not all([subject, subject_type, relation, obj, obj_type]):
                    continue

                src_entity = (
                    db.query(GraphEntity)
                    .filter(GraphEntity.name == subject, GraphEntity.label == subject_type,
                            GraphEntity.doc_id == doc_id)
                    .first()
                )
                if not src_entity:
                    src_entity = GraphEntity(name=subject, label=subject_type, doc_id=doc_id)
                    db.add(src_entity)
                    db.flush()

                tgt_entity = (
                    db.query(GraphEntity)
                    .filter(GraphEntity.name == obj, GraphEntity.label == obj_type,
                            GraphEntity.doc_id == doc_id)
                    .first()
                )
                if not tgt_entity:
                    tgt_entity = GraphEntity(name=obj, label=obj_type, doc_id=doc_id)
                    db.add(tgt_entity)
                    db.flush()

                existing_rel = (
                    db.query(GraphRelation)
                    .filter(
                        GraphRelation.source_entity_id == src_entity.id,
                        GraphRelation.target_entity_id == tgt_entity.id,
                        GraphRelation.relation == relation,
                        GraphRelation.doc_id == doc_id,
                    )
                    .first()
                )
                if not existing_rel:
                    db.add(GraphRelation(
                        source_entity_id=src_entity.id,
                        target_entity_id=tgt_entity.id,
                        relation=relation,
                        doc_id=doc_id,
                    ))

            db.commit()
            logger.info(f"图谱抽取完成 doc={doc_id}, entities={len(all_triples)}, file={original_filename}")
            return True
        except Exception as e:
            db.rollback()
            logger.error(f"图谱抽取写入 DB 失败 doc={doc_id}: {e}")
            return False
        finally:
            db.close()

    def delete_by_doc(self, doc_id: int) -> int:
        db = SessionLocal()
        try:
            entity_ids = [
                r[0] for r in db.query(GraphEntity.id)
                .filter(GraphEntity.doc_id == doc_id).all()
            ]
            if entity_ids:
                db.query(GraphRelation).filter(GraphRelation.doc_id == doc_id).delete()
                db.query(GraphEntity).filter(GraphEntity.doc_id == doc_id).delete()
                db.commit()
            return len(entity_ids)
        except Exception as e:
            db.rollback()
            logger.error(f"图谱删除失败 doc={doc_id}: {e}")
            return 0
        finally:
            db.close()

    def get_stats(self) -> dict:
        db = SessionLocal()
        try:
            total_entities = db.query(GraphEntity).count()
            total_relations = db.query(GraphRelation).count()
            rows = db.query(GraphEntity.label, db.func.count(GraphEntity.id)).group_by(GraphEntity.label).all()
            by_label = {row[0]: row[1] for row in rows}
            return {"total_entities": total_entities, "total_relations": total_relations, "by_label": by_label}
        finally:
            db.close()

    def query_entities(self, page: int = 1, page_size: int = 20,
                       label: str | None = None, keyword: str | None = None) -> dict:
        db = SessionLocal()
        try:
            q = db.query(GraphEntity)
            if label:
                q = q.filter(GraphEntity.label == label)
            if keyword:
                safe = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                q = q.filter(GraphEntity.name.like(f"%{safe}%", escape="\\"))
            total = q.count()
            entities = q.order_by(GraphEntity.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
            total_pages = (total + page_size - 1) // page_size if total else 0
            return {
                "entities": [e.to_dict() for e in entities],
                "total": total, "page": page, "page_size": page_size, "total_pages": total_pages,
            }
        finally:
            db.close()

    def get_entity(self, entity_id: int) -> dict | None:
        db = SessionLocal()
        try:
            entity = db.query(GraphEntity).filter(GraphEntity.id == entity_id).first()
            if not entity:
                return None
            rels = (
                db.query(GraphRelation)
                .filter(
                    (GraphRelation.source_entity_id == entity_id) |
                    (GraphRelation.target_entity_id == entity_id)
                )
                .all()
            )
            neighbor_ids = set()
            for r in rels:
                if r.source_entity_id != entity_id:
                    neighbor_ids.add(r.source_entity_id)
                if r.target_entity_id != entity_id:
                    neighbor_ids.add(r.target_entity_id)
            neighbors = db.query(GraphEntity).filter(GraphEntity.id.in_(neighbor_ids)).all() if neighbor_ids else []
            return {
                "entity": entity.to_dict(),
                "relations": [r.to_dict() for r in rels],
                "neighbors": [n.to_dict() for n in neighbors],
            }
        finally:
            db.close()

    def search_graph(self, query: str, depth: int = 1) -> dict:
        if depth < 1:
            depth = 1
        db = SessionLocal()
        try:
            matched = (
                db.query(GraphEntity)
                .filter(GraphEntity.name.like(f"%{query}%"))
                .limit(20)
                .all()
            )
            if not matched:
                return {"entities": [], "relations": []}

            entity_ids = {e.id for e in matched}
            all_entity_ids = set(entity_ids)
            all_relations = []

            visited = set(entity_ids)
            frontier = list(entity_ids)
            for _ in range(depth):
                if not frontier:
                    break
                rels = (
                    db.query(GraphRelation)
                    .filter(
                        GraphRelation.source_entity_id.in_(frontier) |
                        GraphRelation.target_entity_id.in_(frontier)
                    )
                    .all()
                )
                all_relations.extend(rels)
                next_frontier = set()
                for r in rels:
                    if r.source_entity_id not in visited:
                        next_frontier.add(r.source_entity_id)
                        visited.add(r.source_entity_id)
                    if r.target_entity_id not in visited:
                        next_frontier.add(r.target_entity_id)
                        visited.add(r.target_entity_id)
                frontier = list(next_frontier)
                all_entity_ids.update(frontier)

            entities = db.query(GraphEntity).filter(GraphEntity.id.in_(all_entity_ids)).all()
            return {
                "entities": [e.to_dict() for e in entities],
                "relations": [r.to_dict() for r in all_relations],
            }
        finally:
            db.close()

    def rebuild(self, doc_id: int) -> bool:
        from app.backend.db.models import Document as DocModel

        doc_path = None
        mime_type = None
        original_name = ""
        with SessionLocal() as s:
            doc = s.query(DocModel).filter(DocModel.id == doc_id).first()
            if not doc:
                return False
            doc_path = doc.storage_path
            mime_type = doc.mime_type
            original_name = doc.original_filename

        if not doc_path or not Path(doc_path).exists():
            return False

        self.delete_by_doc(doc_id)
        ok = self.extract_entities(doc_id, doc_path, mime_type, original_name)
        with SessionLocal() as s:
            doc = s.query(DocModel).filter(DocModel.id == doc_id).first()
            if doc:
                doc.is_graph_extracted = ok
                s.commit()
        return ok


kg_service = KnowledgeGraphService()
