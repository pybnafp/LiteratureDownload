import logging
from logging import Logger
from pathlib import Path
from typing import Optional


def setup_logging(
    log_file: str = "download.log",
    level: int = logging.INFO,
    fmt: str = "%(asctime)s - %(levelname)s - %(name)s - %(message)s",
) -> Logger:
    """
    统一配置项目日志：
    - 所有日志同时输出到控制台（stderr）和日志文件；
    - 再次调用时会先清空旧 handler，避免重复打印。
    """
    logger = logging.getLogger()
    logger.setLevel(level)

    # 清除已有的所有 handler（避免 basicConfig 多次调用导致的重复输出）
    for h in list(logger.handlers):
        logger.removeHandler(h)

    # 日志格式
    formatter = logging.Formatter(fmt)

    # 控制台输出
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 文件输出（追加模式）
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    logger.debug("日志系统已初始化，输出到控制台和文件: %s", log_path)
    return logger

