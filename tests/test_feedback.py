"""app/feedback.py의 사후검증 집계·자동조정 안전장치 회귀 테스트 (네트워크 호출 없음).

critical-reviewer 지적(2026-09-16) 사항 위주로 검증한다: 1일 판정은 리포트 전용이며 가중치
자동조정에는 절대 쓰이지 않는지, 매도 구조적 게이트 제외, 재조정 쿨다운(같은 표본 풀 매일
재적용 방지).
"""
import json
import tempfile
import unittest
from pathlib import Path

from app import feedback as fb


class ResolvedOutcomeForWeightingTest(unittest.TestCase):
    def test_1day_alone_never_resolves_for_weighting(self):
        """1일 판정만 나와 있어도(1주/2주 대기중) 가중치 집계에는 쓰이지 않는다."""
        r = {"1day": "적중", "1week": "대기중", "2week": "대기중"}
        self.assertIsNone(fb._resolved_outcome_for_weighting(r))

    def test_prefers_2week_then_1week_ignoring_1day(self):
        r = {"1day": "과잉감지", "1week": "적중", "2week": "대기중"}
        self.assertEqual(fb._resolved_outcome_for_weighting(r), "적중")

    def test_display_fallback_reaches_1day(self):
        """표시용(이력 노출)은 1일까지 폴백하지만, 이는 자동조정과 별개다."""
        outcome, window = fb._resolved_outcome_with_window(
            {"2week": "대기중", "1week": "대기중", "1day": "적중"}
        )
        self.assertEqual((outcome, window), ("적중", "1day"))


class AggregateBasisStatsTest(unittest.TestCase):
    def test_sell_gate_structural_records_excluded(self):
        results = [
            {"bases": ["price_decline"], "score": None, "1week": "적중"},  # 매도 구조규칙, 제외돼야 함
            {"bases": ["price_decline"], "score": 1.0, "1week": "적중"},
            {"bases": ["price_decline"], "score": 1.0, "1week": "과잉감지"},
        ]
        stats = fb._aggregate_basis_stats(results)
        self.assertEqual(stats["price_decline"], {"hits": 1, "total": 2})

    def test_1day_only_records_not_aggregated_for_weighting(self):
        """1주/2주가 아직 대기중이고 1일 판정만 있는 레코드는 집계에서 완전히 빠져야 한다."""
        results = [{"bases": ["price_decline"], "score": 1.0, "1day": "적중",
                    "1week": "대기중", "2week": "대기중"}]
        self.assertEqual(fb._aggregate_basis_stats(results), {})


class AdjustWeightsCooldownTest(unittest.TestCase):
    """critical-reviewer 지적: 재조정 쿨다운 없으면 같은 표본 풀이 매일 재평가되어
    '1회 조정 폭 ±10%' 안전장치가 매일 복리로 적용되는 것과 같아진다."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.weights_path = self.tmp_dir / "weights.json"
        self.adjust_path = self.tmp_dir / "weight_adjustments.jsonl"
        self.weights_path.write_text(json.dumps({"price_decline": 1.0}), encoding="utf-8")
        self._orig_weights_path = fb.WEIGHTS_PATH
        self._orig_adjust_path = fb.WEIGHT_ADJUST_LOG_PATH
        fb.WEIGHTS_PATH = self.weights_path
        fb.WEIGHT_ADJUST_LOG_PATH = self.adjust_path

    def tearDown(self):
        fb.WEIGHTS_PATH = self._orig_weights_path
        fb.WEIGHT_ADJUST_LOG_PATH = self._orig_adjust_path

    def _all_hit_results(self, n):
        return [{"bases": ["price_decline"], "score": 1.0, "1week": "적중"} for _ in range(n)]

    def test_below_min_samples_no_adjustment(self):
        self.assertEqual(fb.adjust_weights(self._all_hit_results(9)), [])

    def test_first_adjustment_at_min_samples(self):
        changes = fb.adjust_weights(self._all_hit_results(10))
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["basis"], "price_decline")
        self.assertAlmostEqual(changes[0]["new_weight"], 1.1)

    def test_same_sample_pool_does_not_readjust_next_day(self):
        results = self._all_hit_results(10)
        first = fb.adjust_weights(results)
        self.assertEqual(len(first), 1)
        # 다음날 재실행: 새 표본 없이 같은 10건을 다시 집계 -> 재조정되면 안 됨
        second = fb.adjust_weights(results)
        self.assertEqual(second, [])

    def test_readjusts_once_enough_new_samples_accumulate(self):
        fb.adjust_weights(self._all_hit_results(10))
        # 새 표본이 MIN_SAMPLES(10)만큼 쌓이기 전(총 19건)에는 재조정 안 됨
        self.assertEqual(fb.adjust_weights(self._all_hit_results(19)), [])
        # 총 20건(직전 조정 시점 10 + 신규 10)에 도달하면 재조정됨
        third = fb.adjust_weights(self._all_hit_results(20))
        self.assertEqual(len(third), 1)


if __name__ == "__main__":
    unittest.main()
