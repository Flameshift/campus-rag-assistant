"""Judge 结构化评分测试。"""

import unittest

from eval.judge_results import derive_score


class JudgeScoreTests(unittest.TestCase):
    def test_all_key_facts_present_scores_two(self):
        item = {"answerable": True, "key_facts": ["甲", "乙"]}
        data = {
            "key_fact_results": [
                {"fact": "甲", "present": True},
                {"fact": "乙", "present": True},
            ],
            "missing_key_facts": [],
            "contradiction": False,
            "off_topic": False,
        }

        self.assertEqual(2, derive_score(item, data))

    def test_merged_key_fact_result_scores_two_when_nothing_is_missing(self):
        item = {"answerable": True, "key_facts": ["甲", "乙"]}
        data = {
            "key_fact_results": [{"fact": "甲和乙", "present": True}],
            "missing_key_facts": [],
            "contradiction": False,
            "off_topic": False,
        }

        self.assertEqual(2, derive_score(item, data))

    def test_missing_key_fact_scores_partial(self):
        item = {"answerable": True, "key_facts": ["甲", "乙"]}
        data = {
            "key_fact_results": [{"fact": "甲", "present": True}],
            "missing_key_facts": ["乙"],
        }

        self.assertEqual(1, derive_score(item, data))

    def test_unanswerable_refusal_scores_two(self):
        item = {"answerable": False, "key_facts": []}

        self.assertEqual(2, derive_score(item, {"refusal_correct": True}))


if __name__ == "__main__":
    unittest.main()
