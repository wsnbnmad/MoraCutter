from __future__ import annotations

import unittest

import numpy as np

from mora_cutter.precision_detection import _ctc_safe_input, _retime_target, _sequence_map


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
