import threading
import time


class RateLimiter:
    """
    Token bucket rate limiter для GitHub API.

    GitHub лимиты: 5000 requests/hour для authenticated requests.
    Используем консервативный лимит 4800/hour с резервом для других операций.
    """

    def __init__(
        self,
        max_requests: int = 4800,
        time_window_seconds: int = 3600,  # 1 hour
        reserve_tokens: int = 200  # Резерв для других операций
    ):
        """
        Инициализирует rate limiter.

        Args:
            max_requests: Максимальное количество запросов в окне времени
            time_window_seconds: Окно времени в секундах (по умолчанию 1 час)
            reserve_tokens: Резерв токенов для других операций
        """
        self.max_requests = max_requests - reserve_tokens
        self.time_window = time_window_seconds
        self.tokens = self.max_requests
        self.last_refill = time.time()
        self.lock = threading.Lock()

        # Минимальная задержка между запросами (мс) для распределения нагрузки
        self.min_delay_ms = (time_window_seconds * 1000) / max_requests

    def acquire(self, tokens: int = 1) -> None:
        """
        Блокирует поток до получения токена.
        Thread-safe операция.

        Args:
            tokens: Количество токенов для получения
        """
        with self.lock:
            self._refill_tokens()

            # Ждем пока не будут доступны токены
            while self.tokens < tokens:
                time.sleep(0.1)
                self._refill_tokens()

            self.tokens -= tokens

            # Добавляем минимальную задержку для равномерного распределения
            time.sleep(self.min_delay_ms / 1000)

    def _refill_tokens(self) -> None:
        """
        Пополняет токены на основе прошедшего времени.
        Вызывается только из-под lock.
        """
        now = time.time()
        elapsed = now - self.last_refill

        if elapsed >= 1:  # Пополняем каждую секунду
            # Вычисляем скорость пополнения (tokens per second)
            refill_rate = self.max_requests / self.time_window
            tokens_to_add = int(elapsed * refill_rate)

            # Не превышаем максимум
            self.tokens = min(self.max_requests, self.tokens + tokens_to_add)
            self.last_refill = now

    def get_status(self) -> dict:
        """
        Возвращает текущий статус rate limiter.

        Returns:
            dict с полями:
                - available_tokens: доступные токены
                - max_tokens: максимальное количество токенов
                - utilization_percent: процент использования (0-100)
        """
        with self.lock:
            self._refill_tokens()
            return {
                "available_tokens": self.tokens,
                "max_tokens": self.max_requests,
                "utilization_percent": int((1 - self.tokens / self.max_requests) * 100)
            }
