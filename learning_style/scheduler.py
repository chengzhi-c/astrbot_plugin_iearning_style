import asyncio

from astrbot.api import logger

from .data_manager import DataManager
from .learning_manager import LearningManager


class Scheduler:
    """
    定时任务调度：
    - analysis_task: 定期分析聊天记录（默认 1h）
    - maintenance_task: 合并情境缓冲区到通用/特定（默认 24h）
    """

    def __init__(
        self,
        data_manager: DataManager,
        learning_manager: LearningManager,
        config: dict,
    ):
        self.data_manager = data_manager
        self.learning_manager = learning_manager
        self.config = config
        self.analysis_interval = self._positive_interval(
            "analysis_interval_seconds", 3600
        )
        self.maintenance_interval = self._positive_interval(
            "maintenance_interval_seconds", 86400
        )
        self.analysis_task: asyncio.Task | None = None
        self.maintenance_task: asyncio.Task | None = None
        self.is_running = False

    def _positive_interval(self, key: str, default: int) -> int:
        value = self.config.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            logger.warning(f"配置 {key} 必须是正整数，已回退为 {default}。")
            return default
        return value

    def start(self):
        if not self.is_running:
            self.is_running = True
            self.analysis_task = asyncio.create_task(self._run_analysis())
            self.maintenance_task = asyncio.create_task(self._run_maintenance())
            logger.info("定时任务已启动。")

    async def stop(self):
        if self.is_running:
            self.is_running = False
            tasks = []
            if self.analysis_task:
                self.analysis_task.cancel()
                tasks.append(self.analysis_task)
            if self.maintenance_task:
                self.maintenance_task.cancel()
                tasks.append(self.maintenance_task)

            if tasks:
                try:
                    await asyncio.gather(*tasks, return_exceptions=True)
                except asyncio.CancelledError:
                    pass

            logger.info("定时任务已停止。")

    async def _run_analysis(self):
        while self.is_running:
            await asyncio.sleep(self.analysis_interval)
            logger.info("开始执行周期性聊天记录分析...")
            await self._perform_analysis()

    async def _perform_analysis(self):
        for session_id in self.data_manager.get_history_sessions():
            try:
                result = await self.learning_manager.analyze_and_learn(session_id)
                if not result.ok and result.code != "insufficient_history":
                    logger.warning(f"周期学习跳过: {result.code}")
                await asyncio.sleep(0)
            except Exception:
                logger.exception("周期学习处理会话时出错")
        if not await self.data_manager.force_save():
            logger.error("周期学习结果保存失败，将在后续任务中重试。")

    async def _run_maintenance(self):
        while self.is_running:
            await asyncio.sleep(self.maintenance_interval)
            logger.info("开始执行周期性风格维护...")
            await self._perform_maintenance()
            await asyncio.sleep(0)

    async def _perform_maintenance(self):
        """合并情境缓冲区到通用/特定，不处理已确认的情境。"""
        for session_id in self.data_manager.get_contextual_sessions():
            try:
                self.data_manager.merge_contextual_buffer(session_id)
            except Exception:
                logger.exception("周期维护处理会话时出错")

        if await self.data_manager.force_save():
            logger.info("风格维护完成（情境缓冲合并）。")
        else:
            logger.error("风格维护保存失败，将在后续任务中重试。")
