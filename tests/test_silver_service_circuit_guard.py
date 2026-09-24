"""tests/test_silver_service_circuit_guard.py

Unit tests for t_enrich_html_to_markdown._LLMServiceGuard — 驗證跳脫門檻、成功歸零，
以及多執行緒併發下狀態維持在合理範圍。不 mock LLM / GCS / MongoDB。

這裡的併發測試不宣稱能重現競態。實測在 CPython 3.14（GIL 啟用）上，即使把
sys.setswitchinterval 調到 1e-9、以 8 條執行緒累加 40 萬次，也不會漏算，因為直譯器只在
迴圈回跳與函式呼叫邊界檢查是否換執行緒，方法本體一旦進入就會跑完。鎖是為了在沒有 GIL 的
free-threaded 直譯器上仍然正確，這類環境無法在本測試環境重現，故測試只涵蓋行為正確性。
"""

import os
import threading
import unittest

os.environ.setdefault("ONENOTE_GCS_BUCKET", "fake-bucket")
os.environ.setdefault("ENVIRONMENT", "local")

from task07_silver_service.t_enrich_html_to_markdown import _LLMServiceGuard  # noqa: E402


class TestGuardThreshold(unittest.TestCase):
    """跳脫門檻與歸零行為。"""

    def test_stays_closed_below_threshold(self):
        guard = _LLMServiceGuard(max_consecutive_failures=3, cooldown_seconds=60)
        guard.record_failure()
        guard.record_failure()
        self.assertFalse(guard.is_open())

    def test_trips_at_threshold(self):
        guard = _LLMServiceGuard(max_consecutive_failures=3, cooldown_seconds=60)
        for _ in range(3):
            guard.record_failure()
        self.assertTrue(guard.is_open())

    def test_counter_resets_after_trip(self):
        # 跳脫時把計數歸零，讓冷卻結束後重新累積
        guard = _LLMServiceGuard(max_consecutive_failures=3, cooldown_seconds=60)
        for _ in range(3):
            guard.record_failure()
        self.assertEqual(guard._consecutive, 0)

    def test_success_resets_counter(self):
        guard = _LLMServiceGuard(max_consecutive_failures=3, cooldown_seconds=60)
        guard.record_failure()
        guard.record_failure()
        guard.record_success()
        guard.record_failure()
        guard.record_failure()
        # 成功已把計數歸零，所以這兩次失敗不足以跳脫
        self.assertFalse(guard.is_open())

    def test_success_closes_open_circuit(self):
        guard = _LLMServiceGuard(max_consecutive_failures=1, cooldown_seconds=60)
        guard.record_failure()
        self.assertTrue(guard.is_open())
        guard.record_success()
        self.assertFalse(guard.is_open())

    def test_is_open_does_not_mutate_state(self):
        # is_open 刻意不加鎖，前提是它完全不改狀態
        guard = _LLMServiceGuard(max_consecutive_failures=3, cooldown_seconds=60)
        guard.record_failure()
        before = (guard._consecutive, guard._open_until)
        for _ in range(100):
            guard.is_open()
        self.assertEqual((guard._consecutive, guard._open_until), before)


class TestGuardUnderConcurrency(unittest.TestCase):
    """多執行緒併發下的狀態合理性。不宣稱重現競態，見模組 docstring。"""

    @staticmethod
    def _run_concurrently(targets, times, workers):
        """開 workers 條執行緒，每條輪流呼叫 targets 裡的函式各 times 次。"""
        barrier = threading.Barrier(workers)

        def run(fn):
            barrier.wait()  # 讓所有執行緒盡量同時開始
            for _ in range(times):
                fn()

        threads = [threading.Thread(target=run, args=(targets[i % len(targets)],)) for i in range(workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    def test_concurrent_failures_do_not_exceed_threshold(self):
        guard = _LLMServiceGuard(max_consecutive_failures=5, cooldown_seconds=60)
        self._run_concurrently([guard.record_failure], times=200, workers=8)
        # 不論交錯順序，計數都不該超出門檻，也不該是負數
        self.assertGreaterEqual(guard._consecutive, 0)
        self.assertLess(guard._consecutive, guard.max)
        self.assertTrue(guard.is_open())

    def test_concurrent_mixed_calls_keep_state_consistent(self):
        guard = _LLMServiceGuard(max_consecutive_failures=5, cooldown_seconds=60)
        self._run_concurrently([guard.record_failure, guard.record_success], times=200, workers=8)
        self.assertGreaterEqual(guard._consecutive, 0)
        self.assertLess(guard._consecutive, guard.max)
        # _open_until 只會是 0.0（被 record_success 關閉）或一個時間戳，不會是中間的壞值
        self.assertGreaterEqual(guard._open_until, 0.0)

    def test_concurrent_calls_raise_nothing(self):
        guard = _LLMServiceGuard(max_consecutive_failures=5, cooldown_seconds=60)
        errors = []

        def run(fn):
            try:
                for _ in range(200):
                    fn()
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=run, args=(guard.record_failure,)) for _ in range(4)]
        threads += [threading.Thread(target=run, args=(guard.record_success,)) for _ in range(4)]
        threads += [threading.Thread(target=run, args=(guard.is_open,)) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
