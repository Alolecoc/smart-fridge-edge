import logging


class EventContextFilter(logging.Filter):
    """Give every log line an event field, including library log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "event_id"):
            record.event_id = "-"
        return True


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s %(levelname)s %(name)s event=%(event_id)s %(message)s",
    )
    for handler in logging.getLogger().handlers:
        handler.addFilter(EventContextFilter())
