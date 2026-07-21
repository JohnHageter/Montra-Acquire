"""QSyntaxHighlighter for .acq acquisition protocol scripts."""
from __future__ import annotations

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat


def _fmt(color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(QFont.Weight.Bold)
    if italic:
        f.setFontItalic(True)
    return f


_KEYWORDS = (
    "CAMERA", "WATCH", "SNAPSHOT", "OUTPUTDIR", "ELAPSE", "COUNT",
    "SET", "RECORD", "DELAY", "LOG", "WAITKEY",
    "REPEAT", "END", "DEF", "CALL",
    "LOAD_ROIS", "TIMELAPSE",
    "DAQ_DIGITAL", "DAQ_ANALOG", "DAQ_PULSE",
)

_SUB_WORDS = ("bg", "ref")

# Rules applied in order; later setFormat calls override earlier ones for the same range.
# Priority (highest last): numbers → sub-words → keywords → strings → comments
_INTERP_VARS = ("iter", "count", "video", "subject", "condition", "replicate")

_RULES: list[tuple[str, QTextCharFormat]] = [
    (r"\b\d+(\.\d+)?\b",
     _fmt("#3D9C09")),                                      # numbers — light green
    (r"(?i)\b(?:" + "|".join(_SUB_WORDS) + r")\b",
     _fmt("#6998A3")),                                      # sub-keywords — yellow
    (r"(?i)\b(?:" + "|".join(_KEYWORDS) + r")\b",
     _fmt("#569CD6", bold=True)),                           # keywords — blue bold
    (r'"[^"]*"',
     _fmt("#CE9178")),                                      # strings — orange
    (r"\{(?:" + "|".join(_INTERP_VARS) + r")\}",
     _fmt("#DCDCAA", bold=True)),                           # {variables} — gold bold
    (r"#[^\n]*",
     _fmt("#6A9955", italic=True)),                         # comments — green italic
]


class ScriptHighlighter(QSyntaxHighlighter):
    """Syntax highlighter for .acq protocol scripts."""

    def __init__(self, document):
        super().__init__(document)
        self._rules = [
            (QRegularExpression(pattern), fmt)
            for pattern, fmt in _RULES
        ]

    def highlightBlock(self, text: str) -> None:
        for expr, fmt in self._rules:
            it = expr.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)
