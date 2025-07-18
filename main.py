import tracemalloc
from app import AudioFocusApp, set_dpi_awareness
from logger import logger
from config import config_manager

if __name__ == "__main__":
    tracemalloc.start()
    set_dpi_awareness()
    
    # 从配置初始化日志记录器
    debug_mode = config_manager.get('general.debug_mode', True)
    retention_days = config_manager.get('logging.log_retention_days', 7)
    logger.setup(debug_mode=debug_mode, log_retention_days=retention_days)
    
    app = AudioFocusApp()
    app.mainloop()