"""
Shared unicode blocks mapping for the i18n and utils test suites.

Both :mod:`tests.stratified_packager.toolbelt.test_i18n` and
:mod:`tests.stratified_packager.toolbelt.test_utils` use the same unicode blocks for
testing string-transforming functions, so the dict mapping block names to its characters
lives here rather than being duplicated in each module.
"""

from __future__ import annotations

import unicodedata
from typing import Final

UNICODE_BLOCKS: Final = {
    block_name: "".join(
        chr(code_point)
        for code_point in range(start, end + 1)
        if not unicodedata.category(chr(code_point)).startswith("C")  # Exclude control characters
    )
    for block_name, (start, end) in {
        "Basic Latin": (0x0000, 0x007F),  # ASCII
        "Latin-1 Supplement": (0x0080, 0x00FF),
        "Latin Extended-A": (0x0100, 0x017F),
        "Latin Extended-B": (0x0180, 0x024F),
        "IPA Extensions": (0x0250, 0x02AF),
        "Spacing Modifier Letters": (0x02B0, 0x02FF),
        "Combining Diacritical Marks": (0x0300, 0x036F),
        "Phonetic Extensions": (0x1D00, 0x1D7F),
        "Phonetic Extensions Supplement": (0x1D80, 0x1DBF),
        "Latin Extended Additional": (0x1E00, 0x1EFF),
        "Superscripts and Subscripts": (0x2070, 0x209F),
        "Currency Symbols": (0x20A0, 0x20CF),
        "Letterlike Symbols": (0x2100, 0x214F),
        "Number Forms": (0x2150, 0x218F),
        "Enclosed Alphanumerics": (0x2460, 0x24FF),
        "Latin Extended-C": (0x2C60, 0x2C7F),
        "CJK Compatibility": (0x3300, 0x33FF),
        "Latin Extended-D": (0xA720, 0xA7FF),
        "Latin Extended-E": (0xAB30, 0xAB60),
        "Alphabetic Presentation Forms": (0xFB00, 0xFB4F),
        "Halfwidth and Fullwidth Forms": (0xFF00, 0xFFEF),
        "Latin Extended-F": (0x10780, 0x107BF),
        "Mathematical Alphanumeric Symbols": (0x1D400, 0x1D7FF),
        "Latin Extended-G": (0x1DF00, 0x1DFFF),
        "Enclosed Alphanumeric Supplement": (0x1F100, 0x1F1FF),
    }.items()
}
