"""Logging for the ML endpoint - same format and levels as backend/src/logger.js so the terminals line up.

LEVELS (lowest -> highest; setting LOG_LEVEL shows that level and everything above it):
    debug   - full detail: received claim, engineered features fed to the model, raw model output
    info    - one line per step: request received, validation passed, prediction made
    summary - exactly one line per scored claim
    error   - failures only
Default is "debug" for now; change with LOG_LEVEL=info|summary|error.

Every line is tagged [ML] and carries the TRACE ID sent by the backend (X-Trace-Id = the Claim ID).
"""
import json
import logging
import os
import re
import pathlib
import sys
from logging.handlers import RotatingFileHandler

SUMMARY = 25                                   # custom level between INFO (20) and ERROR (40)
logging.addLevelName(SUMMARY, "SUMMARY")
_LEVELS = {"debug": logging.DEBUG, "info": logging.INFO, "summary": SUMMARY, "error": logging.ERROR}
_COLORS = {"DEBUG": "\033[90m", "INFO": "\033[36m", "SUMMARY": "\033[32;1m", "ERROR": "\033[31;1m"}
_RESET, _GREY, _TAG = "\033[0m", "\033[90m", "\033[33m"
_SECRET = re.compile(r"password|passwd|token|secret|authorization|cookie|api[-_]?key", re.I)
_USE_COLOR = not os.environ.get("NO_COLOR") and sys.stderr.isatty()


def _redact(v, depth=0):
    """Replace secret-looking keys with *** (never print credentials, even at debug level)."""
    if depth > 6 or not isinstance(v, (dict, list)):
        return v
    if isinstance(v, list):
        return [_redact(x, depth + 1) for x in v]
    return {k: "***" if _SECRET.search(str(k)) else _redact(x, depth + 1) for k, x in v.items()}


class _Fmt(logging.Formatter):
    def __init__(self, color=True):
        super().__init__()
        self.color = color and _USE_COLOR
    """'HH:MM:SS.mmm LEVEL [ML] [trace] message' + indented JSON block when data is attached."""

    def format(self, r):
        t = self.formatTime(r, "%H:%M:%S") + f".{int(r.msecs):03d}"
        trace = getattr(r, "trace", None) or "-"
        msg = re.sub(r"[\r\n]+", " ", r.getMessage())                 # stop log injection via newlines
        lvl = r.levelname.ljust(7)
        head = (f"{_GREY}{t}{_RESET} {_COLORS[r.levelname]}{lvl}{_RESET} {_TAG}[ML]{_RESET} {_GREY}[{trace}]{_RESET} {msg}"
                if self.color else f"{t} {lvl} [ML] [{trace}] {msg}")
        data = getattr(r, "data", None)
        if data is not None:
            block = json.dumps(_redact(data), indent=2, default=str)
            head += "\n" + "\n".join("    " + line for line in block.splitlines())
        return head


class MlLogger:
    """Thin wrapper: log.debug(msg, data=None, trace=None) ... log.summary(...)"""

    def __init__(self):
        self._log = logging.getLogger("pmg-ml")
        self._log.propagate = False                                   # do not double-print via the root logger
        if not self._log.handlers:
            h = logging.StreamHandler(sys.stderr)                     # terminal output
            h.setFormatter(_Fmt())
            self._log.addHandler(h)
            # File sink: the same lines (no colour) go to ml_service/logs/pmg-ml.log, rotating at 10 MB.
            log_dir = pathlib.Path(os.environ.get("LOG_DIR") or pathlib.Path(__file__).resolve().parent / "logs")
            log_dir.mkdir(parents=True, exist_ok=True)
            fh = RotatingFileHandler(log_dir / "pmg-ml.log", maxBytes=10 * 1024 * 1024, backupCount=1, encoding="utf-8")
            fh.setFormatter(_Fmt(color=False))
            self._log.addHandler(fh)
        name = os.environ.get("LOG_LEVEL", "debug").lower()
        self.level_name = name if name in _LEVELS else "debug"        # unknown value -> debug
        self._log.setLevel(_LEVELS[self.level_name])

    def _emit(self, level, msg, data, trace):
        self._log.log(level, msg, extra={"trace": trace, "data": data})

    def debug(self, msg, data=None, trace=None):   self._emit(logging.DEBUG, msg, data, trace)
    def info(self, msg, data=None, trace=None):    self._emit(logging.INFO, msg, data, trace)
    def summary(self, msg, data=None, trace=None): self._emit(SUMMARY, msg, data, trace)
    def error(self, msg, data=None, trace=None):   self._emit(logging.ERROR, msg, data, trace)
    def enabled(self, level):                      return self._log.isEnabledFor(_LEVELS[level])


log = MlLogger()
