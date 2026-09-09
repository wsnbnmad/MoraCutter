from __future__ import annotations

import re
import unicodedata


SMALL_COMBINERS = set("ゃゅょぁぃぅぇぉゎャュョァィゥェォヮ")
JAPANESE_RE = re.compile(r"[ぁ-ゖァ-ヺー々〆ヶ]+")


def katakana_to_hiragana(text: str) -> str:
    out: list[str] = []
    for ch in text:
        code = ord(ch)
        if 0x30A1 <= code <= 0x30F6:
            out.append(chr(code - 0x60))
        else:
            out.append(ch)
    return "".join(out)


def split_moras(text: str) -> list[str]:
    """Split kana text into practical Japanese mora units.

    Small vowels and y-kana attach to the previous kana. Sokuon, moraic nasal,
    and long vowel marks remain independent mora units.
    """
    text = katakana_to_hiragana(unicodedata.normalize("NFKC", text))
    result: list[str] = []
    for run in JAPANESE_RE.findall(text):
        for ch in run:
            if ch in SMALL_COMBINERS and result:
                result[-1] += ch
            else:
                result.append(ch)
    return result


def split_characters(text: str) -> list[str]:
    text = katakana_to_hiragana(unicodedata.normalize("NFKC", text))
    return [ch for run in JAPANESE_RE.findall(text) for ch in run]


def split_phoneme_labels(text: str) -> list[str]:
    """A small, dependency-free kana-to-phoneme approximation.

    This is intended for labeling/editor workflow, not linguistic synthesis.
    """
    mapping = {
        "あ": "a", "い": "i", "う": "u", "え": "e", "お": "o",
        "ん": "N", "っ": "Q", "ー": "long",
    }
    result: list[str] = []
    for mora in split_moras(text):
        if mora in mapping:
            result.append(mapping[mora])
        else:
            result.append(mora)
    return result


def labels_for_unit(text: str, unit: str) -> list[str]:
    if unit == "character":
        return split_characters(text)
    if unit == "phoneme":
        return split_phoneme_labels(text)
    return split_moras(text)

