"""综合置信度：检索质量、生成一致性、风险惩罚和动作分级。"""

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import jieba
from langchain_core.documents import Document

from . import config
from .answer_validator import answer_validator

STOPWORDS = {
    "什么",
    "哪些",
    "怎么",
    "如何",
    "是否",
    "可以",
    "需要",
    "这个",
    "那个",
    "学校",
    "学生",
    "的",
    "了",
    "吗",
    "呢",
    "和",
    "或",
    "及",
    "与",
}

DIMENSION_PATTERNS = {
    "time": (r"多久|多长时间|几天|几日内|什么时候|期限|时限", r"\d+\s*(?:个)?(?:工作日|日|天|月|年|小时)"),
    "quantity": (r"多少|几人|几个人|金额|比例|多少分|多少元|多少小时", r"\d+(?:\.\d+)?\s*(?:%|％|元|人|学时|学分|小时|个月|年)"),
    "institution": (r"谁|哪个部门|哪个办公室|哪里|机构", r"学院|教务处|辅导员|委员会|办公室|学生处|学校|部门"),
    "procedure": (r"流程|步骤|怎么处理|如何办理|怎么办", r"申请|提交|审核|审批|批准|办理|复核|复查"),
    "conditions": (r"哪些情况|什么条件|条件是什么|资格", r"条件|情形|情况|须|应当|不得|可以"),
}


@dataclass
class ConfidenceResult:
    overall: float
    retrieval_confidence: float
    generation_confidence: float
    risk_penalty: float
    action: str
    signals: dict[str, float]
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": round(self.overall, 4),
            "retrieval_confidence": round(self.retrieval_confidence, 4),
            "generation_confidence": round(self.generation_confidence, 4),
            "risk_penalty": round(self.risk_penalty, 4),
            "action": self.action,
            "signals": {key: round(value, 4) for key, value in self.signals.items()},
            "reasons": self.reasons,
        }


class ConfidenceEvaluator:
    """根据检索、回答和风险信号计算综合置信度。"""

    def evaluate(
        self,
        question: str,
        answer: str,
        documents: list[Document],
        rewrite: dict | None = None,
        retrieval_query: str | None = None,
        numeric_validation: dict | None = None,
        coverage: dict | None = None,
        query_plan: dict | None = None,
        applicability_scope: dict | None = None,
    ) -> ConfidenceResult:
        if not config.CONFIDENCE_ENABLED:
            return ConfidenceResult(
                1.0,
                1.0,
                1.0,
                0.0,
                "disabled",
                {},
                [],
            )

        numeric_report = numeric_validation
        if numeric_report is None and config.ANSWER_NUMERIC_VALIDATION_ENABLED:
            try:
                numeric_report = answer_validator.validate_numeric_consistency(
                    answer,
                    documents,
                )
            except Exception:
                numeric_report = {"enabled": False}
        numeric_report = numeric_report or {"enabled": False}
        coverage = coverage or {}
        query_plan = query_plan or {}

        retrieval, retrieval_signals = self._retrieval_confidence(question, documents)
        generation, generation_signals = self._generation_confidence(
            question,
            answer,
            documents,
            numeric_report,
        )
        risk, risk_signals, reasons = self._risk_penalty(
            answer,
            documents,
            rewrite or {},
            retrieval,
            numeric_report,
            coverage,
            query_plan,
            applicability_scope or {},
        )
        overall = max(0.0, min(1.0, retrieval * 0.5 + generation * 0.5 - risk))
        action = self._action(overall)
        if (
            str((applicability_scope or {}).get("applicability_mode") or "")
            == "fallback"
            and answer.strip()
        ):
            action = "answer_with_fallback"
        elif (
            str((applicability_scope or {}).get("applicability_mode") or "")
            == "latest_current"
            and answer.strip()
        ):
            action = "answer_with_applicability_notice"

        return ConfidenceResult(
            overall=overall,
            retrieval_confidence=retrieval,
            generation_confidence=generation,
            risk_penalty=risk,
            action=action,
            signals={**retrieval_signals, **generation_signals, **risk_signals},
            reasons=reasons,
        )

    def _retrieval_confidence(
        self,
        question: str,
        documents: list[Document],
    ) -> tuple[float, dict[str, float]]:
        if not documents:
            return 0.0, {
                "rerank_top_score": 0.0,
                "rerank_margin": 0.0,
                "entity_coverage": 0.0,
                "effective_evidence_count": 0.0,
            }

        scores = sorted(
            (
                float(document.metadata.get("rerank_score", 0.0) or 0.0)
                for document in documents
            ),
            reverse=True,
        )
        top_score = scores[0]
        second_score = scores[1] if len(scores) > 1 else 0.0
        margin = max(0.0, min(1.0, (top_score - second_score) / 0.25))

        question_tokens = self._tokens(question)
        evidence_text = "\n".join(document.page_content for document in documents)
        evidence_tokens = self._tokens(evidence_text)
        entity_coverage = (
            len(question_tokens & evidence_tokens) / len(question_tokens)
            if question_tokens
            else 0.5
        )

        effective_keys = set()
        for document in documents:
            metadata = document.metadata
            effective_keys.add(
                metadata.get("parent_key")
                or metadata.get("content_hash")
                or document.page_content
            )
        evidence_count = min(1.0, len(effective_keys) / 3)
        score = max(
            0.0,
            min(
                1.0,
                0.45 * top_score
                + 0.20 * margin
                + 0.25 * entity_coverage
                + 0.10 * evidence_count,
            ),
        )
        return score, {
            "rerank_top_score": top_score,
            "rerank_margin": margin,
            "entity_coverage": entity_coverage,
            "effective_evidence_count": float(len(effective_keys)),
        }

    def _generation_confidence(
        self,
        question: str,
        answer: str,
        documents: list[Document],
        numeric_report: dict,
    ) -> tuple[float, dict[str, float]]:
        clean_answer = self._strip_footer(answer)
        if not clean_answer.strip():
            return 0.0, {
                "claim_support_rate": 0.0,
                "number_match_rate": 0.0,
                "dimension_coverage": 0.0,
                "citation_coverage": 0.0,
            }

        evidence_text = "\n".join(document.page_content for document in documents)
        evidence_tokens = self._tokens(evidence_text)
        sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[。！？!?])|\n+", clean_answer)
            if len(sentence.strip()) >= 6
        ]
        if not sentences:
            sentences = [clean_answer]

        support_count = 0
        for sentence in sentences:
            sentence_tokens = self._tokens(re.sub(r"\[\s*证据\s*\d+\s*\]", "", sentence))
            if sentence_tokens:
                overlap = len(sentence_tokens & evidence_tokens) / len(sentence_tokens)
                if overlap >= 0.2:
                    support_count += 1

        claim_support = support_count / len(sentences)
        citation_count = len(re.findall(r"\[\s*证据\s*\d+\s*\]", clean_answer))
        citation_coverage = min(1.0, citation_count / len(sentences))

        answer_without_citations = re.sub(r"\[\s*证据\s*\d+\s*\]", "", clean_answer)
        answer_numbers = set(self._number_tokens(answer_without_citations))
        evidence_numbers = set(self._number_tokens(evidence_text))
        number_match = (
            len(answer_numbers & evidence_numbers) / len(answer_numbers)
            if answer_numbers
            else 1.0
        )
        numeric_supported_rate = float(
            numeric_report.get("supported_rate", 1.0)
            if numeric_report.get("enabled")
            else 1.0
        )

        dimension_coverage = self._dimension_coverage(question, clean_answer)
        score = max(
            0.0,
            min(
                1.0,
                0.30 * claim_support
                + 0.15 * number_match
                + 0.20 * dimension_coverage
                + 0.15 * citation_coverage
                + 0.20 * numeric_supported_rate,
            ),
        )
        return score, {
            "claim_support_rate": claim_support,
            "number_match_rate": number_match,
            "dimension_coverage": dimension_coverage,
            "citation_coverage": citation_coverage,
            "numeric_supported_rate": numeric_supported_rate,
        }

    def _risk_penalty(
        self,
        answer: str,
        documents: list[Document],
        rewrite: dict,
        retrieval_confidence: float,
        numeric_report: dict,
        coverage: dict,
        query_plan: dict,
        applicability_scope: dict,
    ) -> tuple[float, dict[str, float], list[str]]:
        ambiguity_risk = 0.10 if rewrite.get("used_history") and rewrite.get("slots") else 0.0
        clarification_risk = 0.25 if query_plan.get("needs_clarification") else 0.0
        no_info_conflict = (
            0.25
            if "资料中未提供" in answer and retrieval_confidence >= 0.65
            else 0.0
        )
        conflict_risk = self._evidence_conflict_risk(documents)
        stale_risk = self._stale_source_risk(documents)
        numeric_conflict_risk = (
            0.35 if int(numeric_report.get("conflict_count", 0) or 0) > 0 else 0.0
        )
        unsupported_rate = float(
            numeric_report.get("supported_rate", 1.0)
            if numeric_report.get("enabled")
            else 1.0
        )
        numeric_unsupported_risk = (
            min(0.15, (1.0 - unsupported_rate) * 0.20)
            if unsupported_rate < 1.0
            else 0.0
        )
        coverage_rate = float(coverage.get("coverage_rate", 1.0) or 1.0)
        coverage_risk = min(0.20, (1.0 - coverage_rate) * 0.25)
        applicability_mode = str(
            applicability_scope.get("applicability_mode") or "exact"
        )
        applicability_risk = {
            "fallback": 0.25,
            "latest_current": 0.10,
            "none": 0.50,
        }.get(applicability_mode, 0.0)
        total = min(
            0.80,
            ambiguity_risk
            + clarification_risk
            + no_info_conflict
            + conflict_risk
            + stale_risk
            + numeric_conflict_risk
            + numeric_unsupported_risk
            + coverage_risk
            + applicability_risk,
        )

        reasons: list[str] = []
        if ambiguity_risk:
            reasons.append("问题依赖历史且查询改写后仍存在歧义")
        if clarification_risk:
            reasons.append("问题缺少明确文档或条款指代")
        if no_info_conflict:
            reasons.append("回答声称资料未提供，但检索置信度较高")
        if conflict_risk:
            reasons.append("高排名证据中存在数值冲突")
        if stale_risk:
            reasons.append("证据来源可能较旧")
        if numeric_conflict_risk:
            reasons.append("回答数字与证据中的对象或数值冲突")
        if numeric_unsupported_risk:
            reasons.append("部分回答数字未在证据中找到")
        if coverage_risk:
            reasons.append("部分子问题缺少足够证据覆盖")
        if applicability_risk:
            reasons.append("检索文件适用年级与用户年级不完全匹配")
        return total, {
            "ambiguity_risk": ambiguity_risk,
            "clarification_risk": clarification_risk,
            "no_info_conflict_risk": no_info_conflict,
            "evidence_conflict_risk": conflict_risk,
            "stale_source_risk": stale_risk,
            "numeric_conflict_risk": numeric_conflict_risk,
            "numeric_unsupported_risk": numeric_unsupported_risk,
            "evidence_coverage_risk": coverage_risk,
            "evidence_coverage_rate": coverage_rate,
            "applicability_risk": applicability_risk,
        }, reasons

    @staticmethod
    def _evidence_conflict_risk(documents: list[Document]) -> float:
        if len(documents) < 2:
            return 0.0
        scores = [float(document.metadata.get("rerank_score", 0.0) or 0.0) for document in documents]
        if not scores or max(scores) - min(scores) > 0.35:
            return 0.0
        number_sets = [
            set(re.findall(r"\d+(?:\.\d+)?%?", document.page_content))
            for document in documents[:3]
        ]
        non_empty = [numbers for numbers in number_sets if numbers]
        if len(non_empty) < 2:
            return 0.0
        return 0.08 if any(a != b for index, a in enumerate(non_empty) for b in non_empty[index + 1 :]) else 0.0

    @staticmethod
    def _stale_source_risk(documents: list[Document]) -> float:
        now = datetime.now(timezone.utc)
        for document in documents:
            value = document.metadata.get("published_at") or document.metadata.get("effective_date")
            if not value:
                continue
            try:
                date = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                if date.tzinfo is None:
                    date = date.replace(tzinfo=timezone.utc)
                if (now - date).days > 365 * 5:
                    return 0.08
            except ValueError:
                continue
        return 0.0

    @staticmethod
    def _dimension_coverage(question: str, answer: str) -> float:
        required = []
        for name, (question_pattern, answer_pattern) in DIMENSION_PATTERNS.items():
            if re.search(question_pattern, question):
                required.append((answer_pattern, name))
        if not required:
            return 1.0
        covered = sum(1 for pattern, _ in required if re.search(pattern, answer))
        return covered / len(required)

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {
            token.strip().lower()
            for token in jieba.cut_for_search(text)
            if len(token.strip()) >= 2 and token.strip().lower() not in STOPWORDS
        }

    @staticmethod
    def _number_tokens(text: str) -> list[str]:
        return re.findall(r"\d+(?:\.\d+)?%?", text)

    @staticmethod
    def _strip_footer(answer: str) -> str:
        return answer.split("**信息来源**", 1)[0].strip()

    @staticmethod
    def _action(overall: float) -> str:
        if overall >= config.CONFIDENCE_HIGH_THRESHOLD:
            return "answer"
        if overall >= config.CONFIDENCE_VERIFY_THRESHOLD:
            return "verify"
        if overall >= config.CONFIDENCE_RETRIEVE_THRESHOLD:
            return "retrieve_again"
        return "clarify_or_refuse"


confidence_evaluator = ConfidenceEvaluator()
