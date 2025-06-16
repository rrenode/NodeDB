# nodedb/logging_utils.py
import logging
import warnings

def setup_loguru_logging():
    """If you use Loguru and want NodeDB warnings and internal logs routed through it, call:
        import nodedb
        nodedb.setup_loguru_logging_if_available()
    """
    try:
        import loguru
        from loguru import logger

        class InterceptHandler(logging.Handler):
            def emit(self, record):
                logger.opt(depth=6, exception=record.exc_info).log(record.levelname, record.getMessage())

        logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
        logging.captureWarnings(True)

        logger.debug("Loguru logging setup via NodeDB")
        return True

    except ImportError:
        return False
