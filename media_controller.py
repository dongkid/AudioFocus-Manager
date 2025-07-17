import asyncio
from winrt.windows.media.control import \
    GlobalSystemMediaTransportControlsSessionManager as MediaManager
from logger import logger

def get_app_name_from_source(source_id):
    """
    尝试从 SourceAppUserModelId 中提取一个可读的应用名称。
    例如，从 'SpotifyAB.Spotify' 提取 'Spotify'。
    这是一个启发式方法，可能不完美。
    """
    # 常见模式：Microsoft.ZuneMusic_8wekyb3d8bbwe!Microsoft.ZuneMusic
    if '!' in source_id:
        app_part = source_id.split('!')[0]
        # 通常是 Microsoft.AppName_hash
        parts = app_part.split('.')
        if len(parts) > 1:
            # 移除 Microsoft. 前缀
            name = parts[1].split('_')[0]
            return name
    
    # 常见模式: SpotifyAB.Spotify
    parts = source_id.split('.')
    if len(parts) > 0:
        # 取第一个部分并尝试清理
        name = parts[0]
        if name.endswith("AB"): # 特殊处理Spotify
            name = name[:-2]
        return name
        
    return source_id

async def get_media_sessions():
    """
    异步获取当前所有可控制的媒体会话。

    返回:
        一个字典列表，每个字典包含会话对象、source_id、显示名称和标题。
    """
    logger.log_debug("[媒体控制] 开始获取媒体会话...")
    sessions_list = []
    try:
        manager = await MediaManager.request_async()
        sessions = manager.get_sessions()
        logger.log_debug(f"[媒体控制] 发现 {len(sessions)} 个媒体会话")
        
        for session in sessions:
            try:
                info = await session.try_get_media_properties_async()
                playback_info = session.get_playback_info()
                if info and playback_info:
                    display_name = get_app_name_from_source(session.source_app_user_model_id)
                    
                    # 转换播放状态为可读字符串
                    status = playback_info.playback_status
                    status_str = "Unknown"
                    if status == 4: status_str = "Playing"
                    elif status == 5: status_str = "Paused"
                    elif status == 3: status_str = "Stopped"

                    session_info = {
                        "session": session,
                        "source": session.source_app_user_model_id,
                        "display_name": display_name,
                        "title": info.title,
                        "artist": info.artist,
                        "status": status_str
                    }
                    sessions_list.append(session_info)
                    logger.log_debug(f"[媒体控制] 会话添加: {display_name} - {info.title} ({status_str})")
            except Exception as e:
                logger.log_error(f"[媒体控制] 获取会话属性失败: {str(e)}")
                continue
    except Exception as e:
        logger.log_error(f"[媒体控制] 获取媒体管理器失败: {str(e)}")
    
    logger.log_debug(f"[媒体控制] 获取完成，共 {len(sessions_list)} 个有效会话")
    return sessions_list

async def control_media(session, command):
    """
    向指定的媒体会话发送控制命令。

    参数:
        session: 从 get_media_sessions 获取的会话对象。
        command: 'play' 或 'pause'。
    """
    try:
        logger.log_debug(f"[媒体控制] 发送命令: {command}")
        if command == 'play':
            await session.try_play_async()
            logger.log_debug("[媒体控制] 播放命令已发送")
        elif command == 'pause':
            await session.try_pause_async()
            logger.log_debug("[媒体控制] 暂停命令已发送")
    except Exception as e:
        logger.log_error(f"[媒体控制] 命令执行失败: {str(e)}")