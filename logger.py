import logging
import threading
from logging.handlers import QueueHandler
from queue import Queue
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

class AppLogger:
    """
    Manages application-wide logging.
    This class is a singleton and ensures thread-safe operation for
    asynchronous logging to both console and file.
    It also handles log rotation and cleanup.
    """
    _singleton_instance = None
    _class_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if not cls._singleton_instance:
            with cls._class_lock:
                if not cls._singleton_instance:
                    cls._singleton_instance = super().__new__(cls)
        return cls._singleton_instance

    def __init__(self):
        # This check prevents re-initialization of the instance.
        if hasattr(self, '_is_initialized') and self._is_initialized:
            return
        with self._class_lock:
            if hasattr(self, '_is_initialized') and self._is_initialized:
                return
            
            self._handler = None
            self._env_details_logged = False
            self._processing_queue = Queue(-1)
            self._listener = None
            self._worker_pool = None
            self._is_initialized = True
            self.file_writer = None
            self.console_writer = None

    def setup(self, debug_mode=False, log_retention_days=7):
        """
        Configures and starts the logging system.
        This method can be safely called multiple times.
        """
        if self._handler is not None:
            return  # Already configured

        self._worker_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='LoggerWorker_')

        log_dir = Path("logs")
        try:
            log_dir.mkdir(exist_ok=True)
        except PermissionError:
            log_dir = Path.home() / "audio_focus_manager_logs"
            log_dir.mkdir(exist_ok=True)
        except Exception:
            import tempfile
            log_dir = Path(tempfile.gettempdir()) / "audio_focus_manager_logs"
            log_dir.mkdir(exist_ok=True)
        self.log_directory = log_dir

        self._clean_logs(log_retention_days)

        self._handler = logging.getLogger("AudioFocusManagerApp")
        self._handler.setLevel(logging.DEBUG)

        log_file = self.log_directory / f"app_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        self.file_writer = logging.FileHandler(log_file, encoding='utf-8')
        self.file_writer.setLevel(logging.DEBUG if debug_mode else logging.INFO)

        self.console_writer = logging.StreamHandler()
        self.console_writer.setLevel(logging.DEBUG if debug_mode else logging.INFO)

        log_pattern = '%(asctime)s | %(levelname)-5s | %(message)s'
        formatter = logging.Formatter(log_pattern, datefmt='%Y-%m-%d %H:%M:%S')
        self.file_writer.setFormatter(formatter)
        self.console_writer.setFormatter(formatter)

        self._listener = logging.handlers.QueueListener(
            self._processing_queue, self.file_writer, self.console_writer, respect_handler_level=True
        )
        self._listener.start()

        self._handler.addHandler(QueueHandler(self._processing_queue))
        
        self.log_debug("Logger setup complete.")
        self.log_debug(f"Logging level is {'DEBUG' if debug_mode else 'INFO'}.")
        self.log_debug(f"Logs are stored in: {self.log_directory}")

    def _clean_logs(self, retention_days):
        """Asynchronously removes old and empty log files."""
        def cleanup_job():
            try:
                now = datetime.now()
                removal_log = []
                for log_file in self.log_directory.glob("*.log"):
                    if log_file.stat().st_size == 0:
                        log_file.unlink()
                        removal_log.append(f"Removed empty file: {log_file.name}")
                        continue

                    mod_time = datetime.fromtimestamp(log_file.stat().st_mtime)
                    if (now - mod_time).days >= retention_days:
                        log_file.unlink()
                        removal_log.append(f"Removed outdated file: {log_file.name}")
                
                if removal_log:
                    self.log_debug("Log cleanup job finished.")
                    for msg in removal_log:
                        self.log_debug(f"  -> {msg}")

            except Exception as e:
                self.log_error(f"Error during log cleanup job: {e}")
        
        if self._worker_pool:
            self._worker_pool.submit(cleanup_job)

    def set_debug_mode(self, enabled):
        """Dynamically changes the logging level."""
        level = logging.DEBUG if enabled else logging.INFO
        if self.console_writer:
            self.console_writer.setLevel(level)
        if self.file_writer:
            self.file_writer.setLevel(level)
        
        # The QueueListener needs to be restarted to respect the new handler levels.
        if self._listener:
            self._listener.stop()
            self._listener = logging.handlers.QueueListener(
                self._processing_queue, self.file_writer, self.console_writer, respect_handler_level=True
            )
            self._listener.start()
        self.log_info(f"Log level dynamically set to {'DEBUG' if enabled else 'INFO'}.")

    def log_error(self, *args, exc_info=True):
        if self._handler:
            message = " ".join(map(str, args))
            self._handler.error(message, exc_info=exc_info)

    def log_warning(self, *args):
        if self._handler:
            message = " ".join(map(str, args))
            self._handler.warning(message)

    def log_info(self, *args):
        if self._handler:
            message = " ".join(map(str, args))
            self._handler.info(message)

    def log_debug(self, *args):
        if self._handler:
            if not self._env_details_logged:
                self._log_environment()
            message = " ".join(map(str, args))
            self._handler.debug(message)

    def shutdown(self):
        if self._listener:
            self._listener.stop()
        if self._worker_pool:
            self._worker_pool.shutdown(wait=True)

    def _log_environment(self):
        import platform, os, sys
        env_specs = [
            f"Platform: {platform.system()} {platform.release()}",
            f"Python: {sys.version}",
            f"Working Dir: {os.getcwd()}",
        ]
        for spec in env_specs:
            self._handler.debug(spec)
        self._env_details_logged = True

# Global singleton logger instance
logger = AppLogger()
