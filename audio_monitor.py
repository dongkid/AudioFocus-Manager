import os
import win32api
from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume, IAudioMeterInformation
import psutil
from logger import logger
from config import config_manager

def get_executable_details(exe_path):
    """
    从可执行文件中提取文件描述或产品名称。
    """
    try:
        lang, codepage = win32api.GetFileVersionInfo(exe_path, '\\VarFileInfo\\Translation')[0]
        string_file_info = f'\\StringFileInfo\\{lang:04x}{codepage:04x}\\'
        
        # 优先获取文件描述
        file_description = win32api.GetFileVersionInfo(exe_path, string_file_info + 'FileDescription')
        if file_description:
            return file_description
            
        # 其次获取产品名称
        product_name = win32api.GetFileVersionInfo(exe_path, string_file_info + 'ProductName')
        if product_name:
            return product_name

    except Exception:
        # 发生任何错误，都返回 None
        pass
    return None

def get_audio_playing_apps():
    """
    获取所有具有音频会话的应用，并标识它们是否正在播放。
    """
    logger.log_debug("[音频监控] 开始扫描所有音频会话...")
    apps = []
    sessions = AudioUtilities.GetAllSessions()
    logger.log_debug(f"[音频监控] 发现 {len(sessions)} 个音频会话")

    for session in sessions:
        if not session.Process:
            continue

        try:
            pid = session.ProcessId
            p = psutil.Process(pid)
            process_name = p.name()
            exe_path = p.exe()

            display_name = get_executable_details(exe_path) or process_name
            
            audio_meter = session._ctl.QueryInterface(IAudioMeterInformation)
            peak_value = audio_meter.GetPeakValue()
            is_playing = peak_value > 0.01
            
            app_info = {
                'pid': pid,
                'process_name': process_name,
                'display_name': display_name,
                'is_playing': is_playing,
                'peak_value': peak_value
            }
            apps.append(app_info)
            
            status = "播放中" if is_playing else "静默"
            logger.log_debug(f"[音频监控] 应用: {display_name} ({process_name}), PID: {pid}, 峰值: {peak_value:.4f}, 状态: {status}")

        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            logger.log_warning(f"[音频监控] 进程访问失败: PID {session.ProcessId if session.Process else 'N/A'}, 错误: {str(e)}")
            continue
        except Exception as e:
            logger.log_error(f"[音频监控] 处理会话时发生未知错误: {e}")
            continue

    logger.log_debug(f"[音频监控] 扫描完成，共找到 {len(apps)} 个具有音频会话的应用")
    return apps