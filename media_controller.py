import asyncio
from winrt.windows.media.control import \
    GlobalSystemMediaTransportControlsSessionManager as MediaManager
from logger import logger

class MediaController:
    def __init__(self):
        self.manager = None
        self.loop = asyncio.get_event_loop()

    async def initialize(self):
        """异步初始化MediaManager。"""
        if self.manager:
            logger.log_info("[媒体控制器] MediaManager 已初始化，跳过。")
            return
        try:
            logger.log_info("[媒体控制器] 正在请求 MediaManager...")
            self.manager = await MediaManager.request_async()
            logger.log_info("[媒体控制器] MediaManager 初始化成功。")
        except Exception as e:
            logger.log_error(f"[媒体控制器] MediaManager 初始化失败: {e}")
            raise

    def get_app_name_from_source(self, source_id):
        """
        尝试从 SourceAppUserModelId 中提取一个可读的应用名称。
        """
        if '!' in source_id:
            app_part = source_id.split('!')[0]
            parts = app_part.split('.')
            if len(parts) > 1:
                name = parts[1].split('_')[0]
                return name
        
        parts = source_id.split('.')
        if len(parts) > 0:
            name = parts[0]
            if name.endswith("AB"):
                name = name[:-2]
            return name
            
        return source_id

    async def get_media_sessions(self):
        """
        异步获取当前所有可控制的媒体会话。
        重用已初始化的 MediaManager 实例。
        """
        if not self.manager:
            logger.log_warning("[媒体控制器] MediaManager 未初始化。")
            return []

        logger.log_debug("[媒体控制器] 开始获取媒体会话...")
        sessions_list = []
        try:
            sessions = self.manager.get_sessions()
            logger.log_debug(f"[媒体控制器] 发现 {len(sessions)} 个媒体会话")
            
            for session in sessions:
                try:
                    info = await session.try_get_media_properties_async()
                    playback_info = session.get_playback_info()
                    if info and playback_info:
                        display_name = self.get_app_name_from_source(session.source_app_user_model_id)
                        
                        status = playback_info.playback_status
                        status_str = "Unknown"
                        if status == 4: status_str = "Playing"
                        elif status == 5: status_str = "Paused"
                        elif status == 3: status_str = "Stopped"

                        session_info = {
                            "source": session.source_app_user_model_id,
                            "display_name": display_name,
                            "title": info.title,
                            "artist": info.artist,
                            "status": status_str
                        }
                        sessions_list.append(session_info)
                        logger.log_debug(f"[媒体控制器] 会话添加: {display_name} - {info.title} ({status_str})")
                except Exception as e:
                    logger.log_error(f"[媒体控制器] 获取会话属性失败: {str(e)}")
                    continue
        except Exception as e:
            logger.log_error(f"[媒体控制器] 获取媒体会话时出错: {str(e)}")
        
        logger.log_debug(f"[媒体控制器] 获取完成，共 {len(sessions_list)} 个有效会话")
        return sessions_list

    async def control_media(self, app_id, command):
        """
        根据 app_id 查找媒体会话并发送控制命令。
        重用已初始化的 MediaManager 实例。
        """
        if not self.manager:
            logger.log_warning("[媒体控制器] MediaManager 未初始化。")
            return

        logger.log_debug(f"[媒体控制器] 尝试对 app_id '{app_id}' 执行 '{command}'")
        try:
            sessions = self.manager.get_sessions()
            
            target_session = None
            for session in sessions:
                if session.source_app_user_model_id == app_id:
                    target_session = session
                    break
            
            if target_session:
                logger.log_debug(f"[媒体控制器] 找到会话，发送命令: {command}")
                if command == 'play':
                    await target_session.try_play_async()
                    logger.log_debug("[媒体控制器] 播放命令已发送")
                elif command == 'pause':
                    await target_session.try_pause_async()
                    logger.log_debug("[媒体控制器] 暂停命令已发送")
            else:
                logger.log_warning(f"[媒体控制器] 未找到 app_id 为 '{app_id}' 的会话")
                
        except Exception as e:
            logger.log_error(f"[媒体控制器] 命令执行失败: {str(e)}")