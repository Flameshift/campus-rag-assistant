"""分层检索指标测试。"""

import unittest

from eval.layer_metrics import _retrieval_metrics


class LayerMetricTests(unittest.TestCase):
    def test_retrieval_metrics_use_source_order(self):
        metrics = _retrieval_metrics([9, 2, 8, 3], {2, 3})

        self.assertEqual(0.0, metrics["recall_at_1"])
        self.assertEqual(0.5, metrics["recall_at_3"])
        self.assertEqual(1.0, metrics["recall_at_5"])
        self.assertAlmostEqual(1 / 3, metrics["precision_at_3"])
        self.assertEqual(0.5, metrics["mrr"])
        self.assertEqual(1.0, metrics["hit_at_3"])


if __name__ == "__main__":
    unittest.main()
