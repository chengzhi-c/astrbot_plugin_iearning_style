"""共享配置校验：正整数 / 布尔值，非法记 warning 并回退默认值。"""

from astrbot.api import logger


def positive_int(config: dict, key: str, default: int) -> int:
    value = config.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        logger.warning(f"配置 {key} 必须是正整数，已回退为 {default}。")
        return default
    return value


def bool_value(config: dict, key: str, default: bool) -> bool:
    value = config.get(key, default)
    if not isinstance(value, bool):
        logger.warning(f"配置 {key} 必须是布尔值，已回退为 {default}。")
        return default
    return value
