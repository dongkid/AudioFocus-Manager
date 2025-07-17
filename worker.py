import asyncio
import time
import psutil
import ctypes
import win32gui
import win32ui
from PIL import Image
import threading

from logger import logger
from audio_monitor import get_audio_playing_apps
from media_controller import get_media_sessions, control_media
from config import config_manager

# 引入一个简单的缓存来存储图标
icon_cache = {}

def get_icon_for_pid(pid):
    """根据进程ID获取应用程序图标，并缓存结果以减少GDI资源消耗。"""
    try:
        proc = psutil.Process(pid)
        exe_path = proc.exe()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None

    if not exe_path:
        return None

    # 如果缓存中已有图标，直接返回
    if exe_path in icon_cache:
        return icon_cache[exe_path]

    large, small = win32gui.ExtractIconEx(exe_path, 0, 1)
    hicon = None
    
    try:
        hicon = large[0] if large else (small[0] if small else None)
        if not hicon:
            # 缓存None结果，避免重复尝试失败的路径
            icon_cache[exe_path] = None
            return None

        icon_info = win32gui.GetIconInfo(hicon)
        
        # 这些是需要手动清理的GDI对象
        hbmColor = icon_info[3]
        hbmMask = icon_info[4]

        try:
            bmp_info = win32gui.GetObject(hbmColor)
            width, height = bmp_info.bmWidth, bmp_info.bmHeight

            hdc = win32ui.CreateDCFromHandle(win32gui.GetDC(0))
            mem_dc = hdc.CreateCompatibleDC()
            save_bit_map = win32ui.CreateBitmap()
            
            try:
                save_bit_map.CreateCompatibleBitmap(hdc, width, height)
                mem_dc.SelectObject(save_bit_map)
                mem_dc.DrawIcon((0, 0), hicon)
                
                bmp_str = save_bit_map.GetBitmapBits(True)
                img = Image.frombuffer('RGBA', (width, height), bmp_str, 'raw', 'BGRA', 0, 1)
                
                # 成功后缓存结果
                icon_cache[exe_path] = img
                return img

            finally:
                # 确保在所有路径上都释放GDI资源
                if save_bit_map.GetHandle():
                    win32gui.DeleteObject(save_bit_map.GetHandle())
                mem_dc.DeleteDC()
                hdc.DeleteDC()

        finally:
            if hbmColor: win32gui.DeleteObject(hbmColor)
            if hbmMask: win32gui.DeleteObject(hbmMask)

    except Exception as e:
        logger.log_error(f"无法为 {exe_path} 提取图标: {e}")
        # 缓存None结果
        icon_cache[exe_path] = None
        return None
    finally:
        # 确保最外层的图标句柄被销毁
        if hicon:
            win32gui.DestroyIcon(hicon)
        # 清理小的图标句柄（如果有）
        for ico in small:
            win32gui.DestroyIcon(ico)

class BackgroundWorker:
    def __init__(self, ui_queue, worker_queue):
        self.ui_queue = ui_queue
        self.worker_queue = worker_queue
        self.stop_event = threading.Event()
        self.last_known_state = None
        
        self.target_app_info = None
        self.was_paused_by_app = False
        self.active_com_sessions = {}
        self.latest_audio_apps_with_icons = []
        self.all_known_apps_cache = {}
        self.delay_timers = {} # 新增：用于跟踪延时模式的应用
        self.lock = threading.Lock()

    def __del__(self):
        print("[GC] BackgroundWorker has been garbage collected.")

    def stop(self):
        logger.log_info("[后台工作线程] 收到停止请求")
        self.stop_event.set()

    def get_latest_audio_apps_with_icons(self):
        """线程安全地获取最新的、包含图标的音频应用列表。"""
        with self.lock:
            return self.latest_audio_apps_with_icons

    def get_all_known_apps(self):
        """线程安全地获取所有已知应用的缓存。"""
        with self.lock:
            return self.all_known_apps_cache.copy()

    def _handle_worker_queue(self, loop):
        try:
            while True:
                message = self.worker_queue.get_nowait()
                msg_type = message.get('type')
                data = message.get('data')
                if msg_type == 'state_update':
                    self.target_app_info = data.get('target')
                    self.was_paused_by_app = data.get('paused', False)
                    logger.log_debug(f"[后台工作线程] 收到状态更新: 目标={self.target_app_info.get('display_name') if self.target_app_info else '无'}")
                elif msg_type == 'force_refresh':
                    self.last_known_state = None
                    logger.log_info("[后台工作线程] 收到强制刷新请求")
                elif msg_type == 'ui_destroyed':
                    self.last_known_state = None
                    logger.log_info("[后台工作线程] 收到UI销毁通知，清除状态缓存")
                elif msg_type == 'config_updated':
                    config_manager.reload_config()
                    logger.log_info("[后台工作线程] 配置已重新加载")
                elif msg_type == 'control_app':
                    self._control_app_playback(loop, data)
        except Exception: # queue.Empty
            pass

    def _control_app_playback(self, loop, data):
        """处理来自UI的播放/暂停控制请求。"""
        source = data.get('source')
        command = data.get('command')
        
        session_to_control = self.active_com_sessions.get(source)
        if not session_to_control:
            logger.log_warning(f"无法找到源为 '{source}' 的活动会话以进行控制。")
            return

        if command == 'toggle':
            try:
                playback_info = session_to_control.get_playback_info()
                status = playback_info.playback_status
                
                if status == 4: # Playing
                    logger.log_info(f"通过UI控制暂停: {source}")
                    loop.run_until_complete(control_media(session_to_control, 'pause'))
                elif status == 5: # Paused
                    logger.log_info(f"通过UI控制播放: {source}")
                    loop.run_until_complete(control_media(session_to_control, 'play'))
                
                # 请求强制刷新以立即更新UI
                self.last_known_state = None
            except Exception as e:
                logger.log_error(f"切换播放状态时出错: {e}")

    def _check_audio_and_control_target(self, loop, audio_apps):
        """根据音频状态控制目标应用，实现新的白名单逻辑。"""
        if not self.target_app_info:
            return

        target_pid = self.target_app_info.get('pid')
        whitelist = config_manager.get('audio.whitelist', {})
        
        # --- 清理不再播放的延时计时器 ---
        playing_app_names = {app['process_name'] for app in audio_apps if app.get('is_playing')}
        for app_name in list(self.delay_timers.keys()):
            if app_name not in playing_app_names:
                del self.delay_timers[app_name]
                logger.log_debug(f"[后台工作线程] 应用 '{app_name}' 已停止播放，从延时计时器中移除。")

        # --- 检查是否有干扰应用 ---
        is_interfering = False
        for app in audio_apps:
            if not app.get('is_playing') or app.get('pid') == target_pid:
                continue

            app_name = app.get('process_name')
            if not app_name:
                continue

            settings = whitelist.get(app_name)
            mode = settings.get('mode') if settings else 'normal'

            if mode == '忽略':
                logger.log_debug(f"[后台工作线程] 应用 '{app_name}' 在白名单中（模式：忽略），已跳过。")
                continue
            
            if mode == '延时':
                delay_seconds = settings.get('delay_seconds', 2)
                if app_name not in self.delay_timers:
                    self.delay_timers[app_name] = time.time()
                    logger.log_debug(f"[后台工作线程] 应用 '{app_name}' 开始播放（模式：延时），启动 {delay_seconds} 秒计时器。")
                    continue # 刚开始，不视为干扰
                
                if time.time() - self.delay_timers[app_name] < delay_seconds:
                    logger.log_debug(f"[后台工作线程] 应用 '{app_name}' 仍在延时期间，暂不处理。")
                    continue # 仍在延时期间，不视为干扰
                
                logger.log_info(f"[后台工作线程] 应用 '{app_name}' 播放超过延时，视为干扰。")

            # 对于 'normal' 模式或延时超时的应用
            is_interfering = True
            logger.log_info(f"[后台工作线程] 检测到干扰应用: {app_name} (模式: {mode})")
            break # 发现一个干扰就足够了

        # --- 根据干扰状态控制目标应用 ---
        target_source = self.target_app_info['source']
        current_target_session = self.active_com_sessions.get(target_source)
        if not current_target_session:
            self.ui_queue.put({'type': 'target_closed'})
            return

        if is_interfering:
            if not self.was_paused_by_app:
                logger.log_info(f"检测到干扰，正在暂停目标: {self.target_app_info.get('display_name')}")
                loop.run_until_complete(control_media(current_target_session, 'pause'))
                self.ui_queue.put({'type': 'set_paused_flag', 'data': True})
        else:
            if self.was_paused_by_app:
                logger.log_info(f"干扰已消失，正在恢复目标: {self.target_app_info.get('display_name')}")
                loop.run_until_complete(control_media(current_target_session, 'play'))
                self.ui_queue.put({'type': 'set_paused_flag', 'data': False})

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        logger.log_info("[后台工作线程] 启动，开始监控音频状态")

        try:
            while not self.stop_event.is_set():
                self._handle_worker_queue(loop)

                try:
                    media_sessions = loop.run_until_complete(get_media_sessions())
                    audio_apps = get_audio_playing_apps()
                    
                    for app in audio_apps:
                        app['icon'] = get_icon_for_pid(app['pid'])

                    with self.lock:
                        self.latest_audio_apps_with_icons = audio_apps
                        for app in audio_apps:
                            if app.get('process_name'):
                                if app['process_name'] not in self.all_known_apps_cache or not self.all_known_apps_cache[app['process_name']].get('icon'):
                                    self.all_known_apps_cache[app['process_name']] = app
                except Exception as e:
                    logger.log_error(f"[后台工作线程] 轮询音频/媒体会话时发生严重错误: {e}")
                    time.sleep(5)
                    continue
                
                # 创建一个从 PID 到音频应用详细信息的映射
                audio_app_details_by_pid = {app['pid']: app for app in audio_apps}

                enriched_sessions = []
                for session_info in media_sessions:
                    # 尝试从会话的显示名称中找到PID
                    display_name_lower = session_info['display_name'].lower()
                    pid_map = {app['process_name'].lower().replace('.exe', ''): app['pid'] for app in audio_apps}
                    pid = pid_map.get(display_name_lower)
                    
                    session_info['pid'] = pid
                    session_info['icon'] = get_icon_for_pid(pid) if pid else None
                    
                    # 如果找到了PID，就从audio_apps中合并更详细的信息
                    if pid and pid in audio_app_details_by_pid:
                        audio_details = audio_app_details_by_pid[pid]
                        session_info['process_name'] = audio_details.get('process_name')
                        session_info['peak_value'] = audio_details.get('peak_value')
                        # 优先使用来自可执行文件的更详细的显示名称
                        session_info['display_name'] = audio_details.get('display_name', session_info['display_name'])

                    enriched_sessions.append(session_info)

                self.active_com_sessions = {s['source']: s['session'] for s in enriched_sessions}
                
                current_state_for_ui = {s['source']: {k: v for k, v in s.items() if k != 'session'} for s in enriched_sessions}

                if current_state_for_ui != self.last_known_state:
                    sessions_for_ui_cleaned = []
                    for s_info in enriched_sessions:
                        info_copy = s_info.copy()
                        del info_copy['session']
                        sessions_for_ui_cleaned.append(info_copy)
                    self.ui_queue.put({'type': 'update_list', 'data': sessions_for_ui_cleaned})
                    self.last_known_state = current_state_for_ui
                
                self.ui_queue.put({'type': 'update_audio_apps', 'data': audio_apps})

                self._check_audio_and_control_target(loop, audio_apps)

                time.sleep(1)
        finally:
            logger.log_info("[后台工作线程] 开始关闭asyncio事件循环...")
            tasks = asyncio.all_tasks(loop=loop)
            for task in tasks:
                task.cancel()
            group = asyncio.gather(*tasks, return_exceptions=True)
            loop.run_until_complete(group)
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()
            self.active_com_sessions.clear() # 清理最后的引用
            logger.log_info("[后台工作线程] asyncio事件循环已关闭，线程停止运行。")