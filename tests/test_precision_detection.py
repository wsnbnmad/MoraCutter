from __future__ import annotations

import unittest

import numpy as np

from mora_cutter.precision_detection import _ctc_forced_mora_timing, _ctc_safe_input, _retime_target, _sequence_map


class PrecisionAlignmentTests(unittest.TestCase):
    def test_missing_recognized_mora_keeps_following_anchors(self) -> None:
        target = ["\u3042", "\u3044", "\u3046", "\u3048", "\u304a"]
        observed = ["\u3042", "\u3046", "\u3048", "\u304a"]
        self.assertEqual(_sequence_map(target, observed), [0, None, 1, 2, 3])

    def test_retiming_outputs_all_transcript_labels_in_order(self) -> None:
        target = ["\u3042", "\u3044", "\u3046", "\u3048"]
        observed = [(0.0, 0.2, "\u3042", 0.9), (0.2, 0.4, "\u3046", 0.9), (0.4, 0.6, "\u3048", 0.9)]
        actual = _retime_target(target, observed, 0.6)
        self.assertEqual([row[2] for row in actual], target)
        self.assertTrue(all(row[0] < row[1] for row in actual))

    def test_short_ctc_input_is_padded_for_the_feature_extractor(self) -> None:
        padded = _ctc_safe_input(np.zeros(12, dtype=np.float32))
        self.assertEqual(len(padded), 8000)

    def test_ctc_forced_alignment_uses_spoken_token_frames(self) -> None:
        class Tokenizer:
            pad_token_id = 0
            unk_token_id = -1

            @staticmethod
            def get_vocab():
                return {"\u3042": 1, "\u3044": 2}

        # Blank, あ, blank, い, blank.  The expected spans are deliberately
        # uneven to guard against returning equal-duration partitions.
        probabilities = np.array([
            [0.99, 0.005, 0.005], [0.02, 0.97, 0.01], [0.02, 0.97, 0.01],
            [0.99, 0.005, 0.005], [0.01, 0.01, 0.98], [0.01, 0.01, 0.98],
            [0.01, 0.01, 0.98], [0.99, 0.005, 0.005],
        ], dtype=np.float32)
        actual = _ctc_forced_mora_timing(np.log(probabilities), Tokenizer(), ["\u3042", "\u3044"], 0.8)
        self.assertEqual([row[2] for row in actual], ["\u3042", "\u3044"])
        self.assertLess(actual[0][1], actual[1][0] + 0.11)
        self.assertGreater(actual[1][1] - actual[1][0], actual[0][1] - actual[0][0])
