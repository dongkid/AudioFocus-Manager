import os
import time
import win32api
from pycaw.pycaw import AudioUtilities, IAudioMeterInformation
import psutil
from logger import logger
from cachetools import TTLCache
from threading import RLock

# --- 缓存 ---
executable_details_cache = TTLCache(maxsize=256, ttl=3600)
executable_details_lock = RLock()

def get_executable_details(exe_path):
    with executable_details_lock:
        if exe_path in executable_details_cache:
            logger.log_debug(f"[文件详情缓存] 命中: {exe_path}")
            return executable_details_cache[exe_path]
    
    logger.log_debug(f"[文件详情缓存] 未命中，开始读取: {exe_path}")
    details = None
    try:
        lang, codepage = win32api.GetFileVersionInfo(exe_path, '\\VarFileInfo\\Translation')[0]
        string_file_info = f'\\StringFileInfo\\{lang:04x}{codepage:04x}\\'
        file_description = win32api.GetFileVersionInfo(exe_path, string_file_info + 'FileDescription')
        details = file_description or win32api.GetFileVersionInfo(exe_path, string_file_info + 'ProductName')
        logger.log_debug(f"[文件详情缓存] 读取成功: {details}")
    except Exception as e:
        logger.log_warning(f"[文件详情缓存] 读取失败: {exe_path}, 错误: {e}")
        pass
    with executable_details_lock:
        executable_details_cache[exe_path] = details
        logger.log_debug(f"[文件详情缓存] 已缓存 '{exe_path}' 的结果: {details}")
    return details

class AudioMonitor:
    """
    一个无状态的音频监控器，用于获取当前正在播放音频的应用程序。
    遵循“即用即取，用完即弃”的原则，以防止COM对象泄漏。
    """
    def get_audio_playing_apps(self):
        """
        获取当前所有正在播放音频的应用列表。
        此方法在每次调用时都会获取全新的会话列表，以确保COM对象被正确释放。
        """
        apps = []
        try:
            sessions = AudioUtilities.GetAllSessions()
        except Exception as e:
            logger.log_error(f"[音频监控] 获取音频会话时出错: {e}")
            return []

        for session in sessions:
            if not session.Process:
                continue
            
            try:
                pid = session.ProcessId
                p = psutil.Process(pid)
                process_name = p.name()
                exe_path = p.exe()
                
                display_name = get_executable_details(exe_path) or process_name
                
                # 直接查询并使用，不缓存COM对象
                audio_meter = session._ctl.QueryInterface(IAudioMeterInformation)
                peak_value = audio_meter.GetPeakValue()
                is_playing = peak_value > 0.01
                
                apps.append({
                    'pid': pid,
                    'process_name': process_name,
                    'display_name': display_name,
                    'is_playing': is_playing,
                    'peak_value': peak_value
                })
            except psutil.NoSuchProcess:
                # 进程在查询期间关闭是正常现象
                continue
            except Exception as e:
                # 捕获其他潜在错误，例如权限问题
                logger.log_warning(f"[音频监控] 处理会话PID {session.ProcessId} ({process_name if 'process_name' in locals() else 'N/A'}) 时出错: {e}")
                continue
        
        logger.log_debug(f"[音频监控] 轮询完成，发现 {len(apps)} 个活动会话。")
        return apps