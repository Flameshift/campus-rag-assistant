"""回答的确定性校验：子问题覆盖与数字对象一致性。"""

import re
from dataclasses import dataclass

import jieba
from langchain_core.documents import Document


STOPWORDS = {
    "这个",
    "那个",
    "哪些",
    "什么",
    "怎么",
    "如何",
    "是否",
    "可以",
    "需要",
    "学校",
    "学生",
    "以及",
    "另外",
    "同时",
    "根据",
    "相关",
    "规定",
    "方面",
    "满分",
    "总分",
    "分值",
    "评分",
    "赋分",
    "评定",
    "考核",
    "标准",
    "等级",
    "优秀",
    "良好",
    "合格",
    "不合格",
    "综合",
    "评价",
    "采用",
    "量化",
    "定性",
    "方法",
    "进行",
    "符合",
    "应当",
}
NUMBER_PATTERN = re.compile(
    r"(?P<number>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>个工作日|工作日|小时|学分|学时|个月|%|％|分|元|年|月|日|天|人|次|门|名)"
)


@dataclass
class NumericClaim:
    value: str
    unit: str
    context: str
    tokens: set[str]
    subject: str = ""
    subject_tokens: set[str] | None = None
    anchor_context: str = ""
    assignment: bool = False
    chunk_id: int | None = None
    source: str = ""

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "unit": self.unit,
            "context": self.context,
            "subject": self.subject,
            "anchor_context": self.anchor_context,
            "assignment": self.assignment,
            "chunk_id": self.chunk_id,
            "source": self.source,
        }


class AnswerValidator:
    """只做规则校验，不调用模型。"""

    CONTEXT_TOKEN_OVERLAP = 0.35
    CONFLICT_TOKEN_OVERLAP = 0.50
    CONFLICT_MARGIN = 0.12

    def validate_numeric_consistency(
        self,
        answer: str,
        documents: list[Document],
    ) -> dict:
        clean_answer = answer.split("**信息来源**", 1)[0]
        answer_claims = self._extract_claims(clean_answer)
        evidence_claims: list[NumericClaim] = []
        for document in documents:
            chunk_id = document.metadata.get("chunk_id")
            try:
                numeric_chunk_id = int(chunk_id) if chunk_id is not None else None
            except (TypeError, ValueError):
                numeric_chunk_id = None
            source = str(
                document.metadata.get("document_title")
                or document.metadata.get("source")
                or ""
            )
            evidence_claims.extend(
                self._extract_claims(
                    document.page_content,
                    chunk_id=numeric_chunk_id,
                    source=source,
                )
            )

        conflicts: list[dict] = []
        unsupported: list[dict] = []
        supported_count = 0
        for claim in answer_claims:
            supported, conflict = self._match_claim(
                claim,
                evidence_claims,
                documents,
            )
            if conflict is not None:
                conflicts.append(conflict)
            elif supported:
                supported_count += 1
            else:
                unsupported.append(claim.to_dict())

        total = len(answer_claims)
        supported_rate = supported_count / total if total else 1.0
        return {
            "enabled": True,
            "claim_count": total,
            "supported_count": supported_count,
            "supported_rate": round(supported_rate, 4),
            "conflict_count": len(conflicts),
            "unsupported_count": len(unsupported),
            "conflicts": conflicts,
            "unsupported": unsupported,
        }

    def build_coverage(
        self,
        subquestions: list[str],
        documents: list[Document],
    ) -> dict:
        matrix = []
        for subquestion in subquestions:
            expected = self._tokens(subquestion)
            best_score = 0.0
            best_document: Document | None = None
            for document in documents:
                actual = self._tokens(document.page_content)
                score = (
                    len(expected & actual) / len(expected)
                    if expected
                    else 0.0
                )
                if score > best_score:
                    best_score = score
                    best_document = document
            matrix.append(
                {
                    "subquestion": subquestion,
                    "covered": best_score >= 0.25,
                    "score": round(best_score, 4),
                    "chunk_id": (
                        best_document.metadata.get("chunk_id")
                        if best_document is not None
                        else None
                    ),
                    "source": (
                        best_document.metadata.get("source")
                        if best_document is not None
                        else ""
                    ),
                }
            )
        covered_count = sum(1 for row in matrix if row["covered"])
        return {
            "subquestion_count": len(matrix),
            "covered_count": covered_count,
            "coverage_rate": (
                covered_count / len(matrix) if matrix else 1.0
            ),
            "missing_subquestions": [
                row["subquestion"] for row in matrix if not row["covered"]
            ],
            "matrix": matrix,
        }

    def _match_claim(
        self,
        claim: NumericClaim,
        evidence_claims: list[NumericClaim],
        documents: list[Document],
    ) -> tuple[bool, dict | None]:
        normalized_value = self._normalize_value(claim.value, claim.unit)
        same_value: list[tuple[float, NumericClaim]] = []
        competing: list[tuple[float, NumericClaim]] = []

        for evidence in evidence_claims:
            if evidence.unit != claim.unit:
                continue
            overlap = self._token_overlap(claim.tokens, evidence.tokens)
            subject_overlap = self._token_overlap(
                claim.subject_tokens or set(),
                evidence.subject_tokens or set(),
            )
            item = (max(overlap, subject_overlap), evidence)
            if self._normalize_value(evidence.value, evidence.unit) == normalized_value:
                same_value.append(item)
            else:
                competing.append(item)

        best_support = max(same_value, key=lambda item: item[0], default=(0.0, None))
        code_supported, code_conflict = self._subject_code_match(
            claim,
            evidence_claims,
            documents,
        )
        if code_conflict is not None:
            return False, code_conflict
        if code_supported:
            return True, None

        if best_support[1] is not None and (
            not claim.tokens
            or best_support[0] >= self.CONTEXT_TOKEN_OVERLAP
            or claim.tokens.issubset(best_support[1].tokens)
        ):
            return True, None
        return False, None

    def _subject_code_match(
        self,
        claim: NumericClaim,
        evidence_claims: list[NumericClaim],
        documents: list[Document],
    ) -> tuple[bool, dict | None]:
        codes = {
            code.lower()
            for code in re.findall(r"[A-Za-z]+\d+", claim.anchor_context)
        }
        if not codes or not claim.assignment:
            return False, None

        normalized_answer = self._normalize_value(claim.value, claim.unit)
        candidates: list[NumericClaim] = []
        for evidence in evidence_claims:
            evidence_text = f"{evidence.subject} {evidence.context}".lower()
            if evidence.unit != claim.unit or not evidence.assignment:
                continue
            if any(code in evidence_text for code in codes):
                candidates.append(evidence)

        for document in documents:
            lowered = document.page_content.lower()
            if not any(code in lowered for code in codes):
                continue
            candidates.extend(
                item
                for item in self._extract_claims(
                    document.page_content,
                    chunk_id=self._coerce_chunk_id(
                        document.metadata.get("chunk_id")
                    ),
                    source=str(document.metadata.get("source") or ""),
                )
                if item.unit == claim.unit and item.assignment
            )

        if not candidates:
            return False, None
        unique: dict[tuple[str, str, str], NumericClaim] = {}
        for item in candidates:
            unique.setdefault(
                (item.value, item.unit, item.context),
                item,
            )
        evidence = max(
            unique.values(),
            key=lambda item: self._subject_code_candidate_score(
                claim,
                item,
                codes,
            ),
        )
        if self._normalize_value(evidence.value, evidence.unit) == normalized_answer:
            return True, None
        return False, {
            "answer": claim.to_dict(),
            "evidence": evidence.to_dict(),
            "reason": "带编号的分项满分值与证据冲突",
        }

    @staticmethod
    def _subject_code_candidate_score(
        claim: NumericClaim,
        evidence: NumericClaim,
        codes: set[str],
    ) -> float:
        score = max(
            AnswerValidator._token_overlap(claim.tokens, evidence.tokens),
            AnswerValidator._token_overlap(
                claim.subject_tokens or set(),
                evidence.subject_tokens or set(),
            ),
        )
        context = f"{evidence.anchor_context} {evidence.context}".lower()
        position = min(
            (
                context.find(code)
                for code in codes
                if code in context
            ),
            default=-1,
        )
        if position >= 0:
            window = context[max(0, position - 40) : position + 80]
            if re.search(r"[=+*×]", window):
                score -= 0.35
            if re.search(r"(?:考核总分|总分|满分)", window):
                score += 0.25
        return score

    @staticmethod
    def _coerce_chunk_id(value) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _extract_claims(
        self,
        text: str,
        chunk_id: int | None = None,
        source: str = "",
    ) -> list[NumericClaim]:
        claims: list[NumericClaim] = []
        for match in NUMBER_PATTERN.finditer(text):
            context = self._context(text, match.start(), match.end())
            subject, subject_tokens = self._extract_subject(text, match.start())
            sentence_start = max(
                text.rfind("。", 0, match.start()),
                text.rfind("\n", 0, match.start()),
            )
            anchor_context = text[
                max(sentence_start + 1, match.start() - 300) : match.start()
            ]
            claims.append(
                NumericClaim(
                    value=match.group("number"),
                    unit=match.group("unit"),
                    context=context,
                    tokens=self._tokens(context),
                    subject=subject,
                    subject_tokens=subject_tokens,
                    anchor_context=anchor_context,
                    assignment=self._is_assignment(text, match.start()),
                    chunk_id=chunk_id,
                    source=source,
                )
            )
        return claims

    @staticmethod
    def _context(text: str, start: int, end: int) -> str:
        left_boundary = max(
            text.rfind("。", 0, start),
            text.rfind("；", 0, start),
            text.rfind(";", 0, start),
            text.rfind("\n", 0, start),
        )
        prefix = text[left_boundary + 1 : start][-240:]
        suffix = text[end : min(len(text), end + 12)]
        return f"{prefix}【{text[start:end]}】{suffix}".strip()

    def _extract_subject(self, text: str, start: int) -> tuple[str, set[str]]:
        prefix = text[max(0, start - 96) : start]
        prefix = re.split(r"[。；;\n]", prefix)[-1]
        prefix = re.sub(
            r"^[\s\d.、,，)）*#>\-]+",
            "",
            prefix,
        )
        prefix = re.sub(
            r"(?:满分|最高|为|是|达到|共计|合计|不超过|不少于)\s*$",
            "",
            prefix,
        ).strip()
        prefix = prefix[-56:].strip(" ：:，,、")
        return prefix, self._tokens(prefix)

    @staticmethod
    def _is_assignment(text: str, start: int) -> bool:
        prefix = text[max(0, start - 18) : start]
        prefix = re.sub(r"[*`\s]+$", "", prefix)
        return bool(
            re.search(
                r"(?:满分|总分为|总分是|最高为|总额为|标准为)"
                r"(?:共|合计为|总计)?\s*$",
                prefix,
            )
        )

    @staticmethod
    def _normalize_value(value: str, unit: str) -> str:
        if unit in {"%", "％"}:
            return f"{float(value):g}%"
        return f"{float(value):g}{unit}"

    @staticmethod
    def _tokens(text: str) -> set[str]:
        cleaned = NUMBER_PATTERN.sub(" ", text)
        return {
            token.strip().lower()
            for token in jieba.cut_for_search(cleaned)
            if len(token.strip()) >= 2 and token.strip().lower() not in STOPWORDS
        }

    @staticmethod
    def _token_overlap(left: set[str], right: set[str]) -> float:
        if not left:
            return 0.0
        return len(left & right) / len(left)


answer_validator = AnswerValidator()
