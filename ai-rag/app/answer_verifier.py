"""回答完整性复核与一次补全。

复核器只检查当前问题是否被给定证据完整、无矛盾地回答，不引入外部知识。
发现问题时，使用原问题和原证据重新生成一次回答，避免遗漏直接条款中的必要事实。
"""

import json
import logging
import re

from langchain_core.documents import Document
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from . import config
from .answer_validator import answer_validator
from .citations import build_evidence_context

logger = logging.getLogger(__name__)

VERIFY_PROMPT = """你是 RAG 回答完整性复核器。请只依据【参考资料】检查【模型回答】。

检查原则：
1. 先从参考资料中找出直接回答用户问题的核心条款，并以完整条款为单位检查，不能只截取第一句。
2. 核心条款包括同一条、同一段落中紧接在条件句后的结果、处理后果、适用范围和例外。
3. 列出该核心条款中，为完整回答当前情境而必须出现的对象、条件、时间、结果、处理后果和例外。
4. 逐项检查模型回答；不要只检查问题中的疑问词是否得到回答。
5. 同一核心条款把某项结果、例外或适用范围与用户情境直接绑定，而回答未提及时，必须判为缺失。
6. 如果用户询问时间、条件或范围，而核心条款紧接着说明该时间或条件对应的注册、取得资格、延长、取消等结果，这些结果是回答的必要组成部分。
7. 不要要求补充与问题无关的背景或解释性细节，也不要引入外部知识。
8. 只把参考资料已经提供、但在回答中缺失的事实列为 missing_requirements。
9. 只把与参考资料明确冲突或没有资料支持的事实列为 contradictions 或 unsupported_claims。
10. 对清单、枚举或多条件条款，检查回答是否覆盖与用户对象直接相关的完整类别边界，不能只列部分示例。
11. 如果问题询问总分、满分或总量，回答必须明确核心对象的总量；只列分项或只列部分对象时，必须列为 missing_requirements。

输出 JSON，不要输出其他内容：
{{"direct_clause":"","fact_checks":[{{"fact":"必须出现的必要事实","present":true}}],"missing_requirements":[],"contradictions":[],"unsupported_claims":[]}}

【对话历史】
{history}

【用户问题】
{question}

【参考资料】
{context}

【模型回答】
{answer}
"""

REPAIR_PROMPT = """你是 RAG 回答修复器。请依据【参考资料】补全【原回答】。

要求：
1. 只使用参考资料，不引入外部知识。
2. 补齐复核指出的遗漏事实；如果某项资料未提供，不要猜测。
3. 保持简洁，先给结论，再列出必要依据。
4. 事实后的证据编号必须与参考资料编号一致。
5. 只输出回答正文，不要添加“信息来源”列表。
6. 数字冲突必须回到证据原文，定位相同对象、编号或分项的值后重写，不能保留原数字。

【用户问题】
{question}

【对话历史】
{history}

【参考资料】
{context}

【原回答】
{answer}

【需要修复的问题】
{issues}
"""


class AnswerVerifier:
    """对生成回答做一次结构化复核，并在必要时补全。"""

    def __init__(self) -> None:
        self._llm: ChatOpenAI | None = None

    @property
    def enabled(self) -> bool:
        return config.ANSWER_VERIFICATION_ENABLED and bool(config.LLM_API_KEY)

    def review_and_repair(
        self,
        question: str,
        answer: str,
        documents: list[Document],
        history: str,
    ) -> tuple[str, dict]:
        """返回最终回答和复核报告；未发现问题时原样返回。"""
        numeric_report = self._numeric_report(answer, documents)
        numeric_issues = self._numeric_issues(numeric_report)
        if not self.enabled or not answer.strip() or not documents:
            return answer, {
                "enabled": self.enabled,
                "checked": False,
                "repaired": False,
                "numeric_validation": numeric_report,
                "issues": numeric_issues,
            }

        report = self._verify(question, answer, documents, history)
        issues = (
            report.get("missing_requirements", [])
            + report.get("contradictions", [])
            + report.get("unsupported_claims", [])
            + numeric_issues
        )
        if report.get("complete") and not issues:
            return answer, {
                "enabled": True,
                "checked": True,
                "repaired": False,
                "complete": True,
                "numeric_validation": numeric_report,
            }

        try:
            repaired = self._repair(question, answer, documents, history, issues)
        except Exception as exc:
            logger.warning("回答补全失败，保留原回答: %s", exc)
            repaired = ""

        final_answer = repaired.strip() if repaired.strip() else answer
        final_report = self._numeric_report(final_answer, documents)
        if repaired.strip():
            return final_answer, {
                "enabled": True,
                "checked": True,
                "repaired": True,
                "complete": False,
                "issues": issues,
                "numeric_validation": final_report,
            }
        return final_answer, {
            "enabled": True,
            "checked": True,
            "repaired": False,
            "complete": False,
            "issues": issues,
            "numeric_validation": final_report,
        }

    def _get_llm(self) -> ChatOpenAI:
        if self._llm is None:
            self._llm = ChatOpenAI(
                model=config.ANSWER_VERIFICATION_MODEL,
                api_key=SecretStr(config.LLM_API_KEY),
                base_url=config.LLM_BASE_URL,
                temperature=0,
                max_completion_tokens=1600,
                timeout=config.ANSWER_VERIFICATION_TIMEOUT,
                max_retries=1,
            )
        return self._llm

    def _verify(
        self,
        question: str,
        answer: str,
        documents: list[Document],
        history: str,
    ) -> dict:
        prompt = VERIFY_PROMPT.format(
            history=history or "（无）",
            question=question,
            context=build_evidence_context(documents),
            answer=answer,
        )
        response = self._get_llm().invoke(prompt)
        content = getattr(response, "content", "") or ""
        match = re.search(r"\{.*\}", content, re.S)
        if not match:
            return {"complete": True, "missing_requirements": [], "contradictions": [], "unsupported_claims": []}
        try:
            data = json.loads(match.group(0))
        except (TypeError, ValueError):
            return {"complete": True, "missing_requirements": [], "contradictions": [], "unsupported_claims": []}
        missing_requirements = self._string_list(data.get("missing_requirements"))
        for check in data.get("fact_checks") or []:
            if not isinstance(check, dict) or bool(check.get("present")):
                continue
            fact = str(check.get("fact") or "").strip()
            if fact and fact not in missing_requirements:
                missing_requirements.append(fact)
        contradictions = self._string_list(data.get("contradictions"))
        unsupported_claims = self._string_list(data.get("unsupported_claims"))
        return {
            "complete": not (missing_requirements or contradictions or unsupported_claims),
            "missing_requirements": missing_requirements,
            "contradictions": contradictions,
            "unsupported_claims": unsupported_claims,
        }

    def _repair(
        self,
        question: str,
        answer: str,
        documents: list[Document],
        history: str,
        issues: list[str],
    ) -> str:
        prompt = REPAIR_PROMPT.format(
            question=question,
            history=history or "（无）",
            context=build_evidence_context(documents),
            answer=answer,
            issues="\n".join(f"- {issue}" for issue in issues) or "- 回答不完整，请依据参考资料补全",
        )
        response = self._get_llm().invoke(prompt)
        return getattr(response, "content", "") or ""

    @staticmethod
    def _string_list(value) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    @staticmethod
    def _numeric_report(answer: str, documents: list[Document]) -> dict:
        if not config.ANSWER_NUMERIC_VALIDATION_ENABLED:
            return {"enabled": False}
        try:
            return answer_validator.validate_numeric_consistency(answer, documents)
        except Exception as exc:
            logger.warning("数字一致性校验失败: %s", exc)
            return {"enabled": False, "error": str(exc)}

    @staticmethod
    def _numeric_issues(report: dict) -> list[str]:
        issues: list[str] = []
        for conflict in report.get("conflicts", []) or []:
            answer_claim = conflict.get("answer") or {}
            evidence_claim = conflict.get("evidence") or {}
            issues.append(
                "数字对象冲突：回答写 "
                f"{answer_claim.get('value', '')}{answer_claim.get('unit', '')}，"
                "对应证据为 "
                f"{evidence_claim.get('value', '')}{evidence_claim.get('unit', '')}。"
            )
        return issues

answer_verifier = AnswerVerifier()
