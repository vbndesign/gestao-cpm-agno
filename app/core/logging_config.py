import json
import logging
from datetime import datetime, timezone

_STDLIB_KEYS = {
    "msg", "args", "levelname", "levelno", "pathname", "filename", "module",
    "exc_info", "exc_text", "stack_info", "lineno", "funcName", "created",
    "msecs", "relativeCreated", "thread", "threadName", "processName",
    "process", "name", "message", "taskName", "asctime",
}


class JsonFormatter(logging.Formatter):
    """Saída estruturada em JSON para produção (parseable por log aggregators)."""

    def format(self, record: logging.LogRecord) -> str:
        data: dict = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        for k, v in record.__dict__.items():
            if k not in _STDLIB_KEYS:
                data[k] = v
        return json.dumps(data, ensure_ascii=False)


def setup_logging(app_env: str, log_level: str) -> None:
    """Configura o logging raiz. Deve ser chamado uma única vez na inicialização."""
    handler = logging.StreamHandler()
    if app_env != "dev":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
    root = logging.getLogger()
    root.setLevel(log_level)
    root.handlers = [handler]
