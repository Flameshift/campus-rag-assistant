"""规则优先的查询规划：时间语义、子问题和指代风险。"""

import re
from dataclasses import asdict, dataclass, field


SPLIT_PATTERN = re.compile(
    r"(?:[?？]+|[;；]|(?:另外|此外|同时|还有|并且|而且))"
)
QUESTION_WORD_PATTERN = re.compile(
    r"(?:什么|哪些|哪个|如何|怎么|是否|多少|多久|几时|何时|谁|哪里)"
)
CONNECTOR_PREFIXES = (
    "另外",
    "此外",
    "同时",
    "以及",
    "还有",
    "并且",
    "而且",
    "那么",
    "请问",
)
AMBIGUOUS_REFERENCE_PATTERN = re.compile(
    r"(?:本办法|该办法|上述办法|前述办法|该规定|上述规定|该文件|上述文件|第一条)"
)
VAGUE_QUESTION_PATTERN = re.compile(
    r"^(?:请问)?(?:这个|那个|这种情况|这件事|上面|前面)"
    r"(?:该)?(?:怎么|如何|要|会|能|可以|是什么|有哪些|严重|有用|重要|正常|合理)"
)
EXPLICIT_DOCUMENT_PATTERN = re.compile(r"《[^》]+》")
SOURCE_CONTEXT_PATTERN = re.compile(
    r"(?:根据|依据|按照|参照|基于)\s*"
    r"(?:上述|前述|以上|相关)?\s*"
    r"(?:学生手册|手册|证据|材料|原文|文件|制度|规定|pdf)"
    r"|学生手册[^\n]{0,24}第\s*\d+\s*页"
    r"|(?:上述|前述|以上)\s*(?:证据|材料|文档|文件|规定)"
)
HISTORICAL_PATTERN = re.compile(
    r"(?:原来|原《|旧版|历史版本|以前|当时|当时有效|废止前|修订前|\b20\d{2}\s*年)"
)
CURRENT_PATTERN = re.compile(r"(?:现行|当前|现在|目前|最新|现行有效)")
COMPARE_PATTERN = re.compile(r"(?:修订前后|新旧版本|前后变化|有什么区别|差异|对比|相比)")
COHORT_TEXT = r"(?:20\d{2}|\d{2}|[〇零一二三四五六七八九]{2,4})"
COHORT_PATTERN = re.compile(rf"(?P<cohort>{COHORT_TEXT})\s*级")
USER_COHORT_PATTERN = re.compile(
    rf"(?:我是|我属于|本人是|作为)\s*(?P<cohort>{COHORT_TEXT})\s*级"
)
TARGET_COHORT_PATTERN = re.compile(
    rf"(?:回答|针对|帮助|供)\s*(?P<cohort>{COHORT_TEXT})\s*级"
)
COHORT_STUDENT_PATTERN = re.compile(
    rf"(?P<cohort>{COHORT_TEXT})\s*级(?:新生|学生)(?:想|请问|咨询|问)"
)
AS_OF_PATTERN = re.compile(
    r"截至\s*(?P<year>20\d{2})\s*年"
    r"(?:\s*(?P<month>\d{1,2})\s*月)?"
    r"(?:\s*(?P<day>\d{1,2})\s*日)?"
)


@dataclass
class QueryPlan:
    """一次问答使用的轻量查询计划。"""

    original_question: str
    retrieval_queries: list[str]
    subquestions: list[str]
    time_intent: str = "current"
    as_of_date: str | None = None
    user_cohort: str = ""
    needs_clarification: bool = False
    clarification_reason: str = ""
    clarification_question: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class QueryPlanner:
    """不调用外部模型，先处理高确定性的查询结构。"""

    MAX_SUBQUESTIONS = 3

    def plan(
        self,
        question: str,
        rewrite: dict | None = None,
        history: list[dict] | None = None,
    ) -> QueryPlan:
        rewrite = rewrite or {}
        history = history or []
        base_query = str(rewrite.get("query") or question).strip()
        rewrite_type = str(rewrite.get("rewrite_type") or "")
        if not history and rewrite_type in {
            "normalize",
            "standalone",
            "long_compress",
            "rule_fallback",
        }:
            original_query = str(
                rewrite.get("normalized_question") or question
            ).strip()
            subquestions = self._merge_subquestions(
                self._split_subquestions(original_query),
                self._split_subquestions(base_query),
            )
        else:
            subquestions = self._split_subquestions(base_query)
        time_intent, as_of_date = self._resolve_time_intent(base_query)
        user_cohort = (
            self._resolve_user_cohort(base_query)
            or self._resolve_user_cohort(question)
        )
        needs_clarification, reason = self._check_clarification(
            question=question,
            history=history,
            used_history=bool(rewrite.get("used_history")),
        )

        retrieval_queries = [base_query]
        for subquestion in subquestions:
            if subquestion != base_query and subquestion not in retrieval_queries:
                retrieval_queries.append(subquestion)

        warnings: list[str] = []
        if needs_clarification:
            warnings.append(reason)
        if time_intent == "historical":
            warnings.append("问题包含历史版本语义，检索不能只限定现行文档")
        if time_intent == "compare":
            warnings.append("问题需要同时比较多个版本")

        return QueryPlan(
            original_question=question,
            retrieval_queries=retrieval_queries,
            subquestions=subquestions or [base_query],
            time_intent=time_intent,
            as_of_date=as_of_date,
            user_cohort=user_cohort,
            needs_clarification=needs_clarification,
            clarification_reason=reason,
            clarification_question=(
                self._clarification_question(reason) if needs_clarification else ""
            ),
            warnings=warnings,
        )

    def _merge_subquestions(self, *groups: list[str]) -> list[str]:
        merged: list[str] = []
        for group in groups:
            for subquestion in group:
                if subquestion and subquestion not in merged:
                    merged.append(subquestion)
                if len(merged) >= self.MAX_SUBQUESTIONS:
                    return merged
        return merged

    def _split_subquestions(self, query: str) -> list[str]:
        parts = []
        for part in SPLIT_PATTERN.split(query):
            candidates = [part]
            if "以及" in part:
                left, right = part.split("以及", 1)
                if len(left.strip()) >= 4 and QUESTION_WORD_PATTERN.search(right):
                    candidates = [left, right]
            for candidate in candidates:
                cleaned = self._clean_part(candidate)
                if len(cleaned) < 4:
                    continue
                if cleaned not in parts:
                    parts.append(cleaned)
                if len(parts) >= self.MAX_SUBQUESTIONS:
                    return parts
        if len(parts) <= 1:
            return [query.strip()] if query.strip() else []
        return parts

    @staticmethod
    def _clean_part(value: str) -> str:
        cleaned = value.strip(" \t\r\n，,。.:：、-")
        changed = True
        while changed:
            changed = False
            for prefix in CONNECTOR_PREFIXES:
                if cleaned.startswith(prefix):
                    cleaned = cleaned[len(prefix) :].lstrip("，,。:： ")
                    changed = True
        return cleaned.strip()

    @staticmethod
    def _resolve_time_intent(query: str) -> tuple[str, str | None]:
        if COMPARE_PATTERN.search(query):
            return "compare", None

        as_of_match = AS_OF_PATTERN.search(query)
        if as_of_match:
            year = int(as_of_match.group("year"))
            month = int(as_of_match.group("month") or 1)
            day = int(as_of_match.group("day") or 1)
            return "as_of", f"{year:04d}-{month:02d}-{day:02d}"

        if HISTORICAL_PATTERN.search(query):
            return "historical", None
        if CURRENT_PATTERN.search(query):
            return "current", None
        return "current", None

    @staticmethod
    def _resolve_user_cohort(query: str) -> str:
        for pattern in (
            USER_COHORT_PATTERN,
            TARGET_COHORT_PATTERN,
            COHORT_STUDENT_PATTERN,
        ):
            match = pattern.search(query)
            if match:
                return QueryPlanner._cohort_from_value(match.group("cohort"))
        return ""

    @staticmethod
    def _cohort_from_value(value: str) -> str:
        text = str(value or "")
        if re.fullmatch(r"20\d{2}", text):
            return text
        if re.fullmatch(r"\d{2}", text):
            return str(2000 + int(text))
        digits = {
            "〇": 0,
            "零": 0,
            "一": 1,
            "二": 2,
            "三": 3,
            "四": 4,
            "五": 5,
            "六": 6,
            "七": 7,
            "八": 8,
            "九": 9,
        }
        if len(text) == 2:
            if all(char in digits for char in text):
                return str(2000 + int("".join(str(digits[char]) for char in text)))
            return ""
        if len(text) == 4 and all(char in digits for char in text):
            return "".join(str(digits[char]) for char in text)
        return ""

    @staticmethod
    def _check_clarification(
        question: str,
        history: list[dict],
        used_history: bool,
    ) -> tuple[bool, str]:
        if history or used_history:
            return False, ""
        if EXPLICIT_DOCUMENT_PATTERN.search(question):
            return False, ""
        if SOURCE_CONTEXT_PATTERN.search(question):
            return False, ""
        if not AMBIGUOUS_REFERENCE_PATTERN.search(question):
            if not VAGUE_QUESTION_PATTERN.search(question):
                return False, ""
            return True, "问题缺少具体事项，无法确定检索对象"
        return True, "问题包含未消解的文档或条款指代，缺少明确制度名称"

    @staticmethod
    def _clarification_question(reason: str) -> str:
        if "制度名称" in reason or "文档" in reason:
            return (
                "请补充具体的制度或文件名称，例如"
                "《陕西师范大学学生管理规定》自何时施行？"
            )
        return "请补充你具体想了解的事项、对象或场景，我再按对应条款回答。"


query_planner = QueryPlanner()
