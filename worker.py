import asyncio
import time
import gc
import psutil
import ctypes
import win32gui
import win32ui
from PIL import Image
import threading
from cachetools import LRUCache
import comtypes

from logger import logger
from audio_monitor import AudioMonitor
from media_controller import MediaController
from config import config_manager

# 使用 LRUCache 替换 dict，并增加线程锁保证安全
icon_cache = LRUCache(maxsize=128)
icon_cache_lock = threading.Lock()

def get_icon_for_pid(pid):
    """根据进程ID获取应用程序图标，并使用线程安全的LRU缓存。"""
    try:
        proc = psutil.Process(pid)
        exe_path = proc.exe()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None

    if not exe_path:
        return None

    with icon_cache_lock:
        if exe_path in icon_cache:
            logger.log_debug(f"[图标缓存] 命中: {exe_path}")
            return icon_cache[exe_path]
        logger.log_debug(f"[图标缓存] 未命中，尝试提取: {exe_path}")

    large, small = [], []
    hicon = None
    try:
        # 1. 获取文件中图标的总数 (2-arg call)
        num_icons = win32gui.ExtractIconEx(exe_path, -1)
        if num_icons == 0:
            with icon_cache_lock:
                icon_cache[exe_path] = None
            return None

        # 2. 提取第一个大图标和第一个小图标 (3-arg call)
        large, small = win32gui.ExtractIconEx(exe_path, 0, 1)

        hicon = large[0] if large else (small[0] if small else None)
        if not hicon:
            with icon_cache_lock:
                icon_cache[exe_path] = None
            return None

        icon_info = win32gui.GetIconInfo(hicon)
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
                
                with icon_cache_lock:
                    icon_cache[exe_path] = img
                    logger.log_debug(f"[图标缓存] 成功提取并缓存图标: {exe_path}")
                return img

            finally:
                if save_bit_map.GetHandle():
                    win32gui.DeleteObject(save_bit_map.GetHandle())
                mem_dc.DeleteDC()
                hdc.DeleteDC()

        finally:
            if hbmColor: win32gui.DeleteObject(hbmColor)
            if hbmMask: win32gui.DeleteObject(hbmMask)

    except Exception as e:
        logger.log_error(f"无法为 {exe_path} 提取图标: {e}")
        with icon_cache_lock:
            icon_cache[exe_path] = None
            logger.log_warning(f"[图标缓存] 提取失败，缓存None: {exe_path}")
        return None
    finally:
        # 3. 确保销毁所有从 ExtractIconEx 获取的句柄
        for ico in large:
            if ico: win32gui.DestroyIcon(ico)
        for ico in small:
            if ico: win32gui.DestroyIcon(ico)

class BackgroundWorker:
    def __init__(self, ui_queue, worker_queue):
        self.ui_queue = ui_queue
        self.worker_queue = worker_queue
        self.stop_event = threading.Event()
        self.last_known_state = None
        
        self.target_app_info = None
        self.was_paused_by_app = False
        self.was_manually_paused = False # 新增：跟踪手动暂停状态
        # self.active_com_sessions 已被移除，以防止COM对象泄漏
        self.latest_audio_apps_with_icons = []
        self.all_known_apps_cache = {}
        self.delay_timers = {} # 新增：用于跟踪延时模式的应用
        self.lock = threading.Lock()

        # 为事件驱动模型新增的属性
        self.loop = None
        self.async_stop_event = None
        self.media_controller = None

        self.audio_monitor = None

    def __del__(self):
        print("[GC] BackgroundWorker has been garbage collected.")

    def stop(self):
        logger.log_info("[后台工作线程] 收到停止请求")
        self.stop_event.set()
        if self.loop and self.async_stop_event and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.async_stop_event.set)

    def get_latest_audio_apps_with_icons(self):
        """线程安全地获取最新的、包含图标的音频应用列表。"""
        with self.lock:
            return self.latest_audio_apps_with_icons

    def get_all_known_apps(self):
        """线程安全地获取所有已知应用的缓存。"""
        with self.lock:
            return self.all_known_apps_cache.copy()

    async def _handle_worker_queue(self):
        try:
            while True:
                message = self.worker_queue.get_nowait()
                msg_type = message.get('type')
                data = message.get('data')
                if msg_type == 'state_update':
                    self.target_app_info = data.get('target')
                    self.was_paused_by_app = data.get('paused', False)
                    # 当目标应用改变或取消时，重置手动暂停标志
                    if not self.target_app_info or (self.last_known_state and self.target_app_info['source'] not in self.last_known_state):
                        self.was_manually_paused = False
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
                    source = data.get('source')
                    status = data.get('status')
                    is_target_app = self.target_app_info and source == self.target_app_info['source']

                    # 如果是目标应用被手动暂停，则设置标志
                    if is_target_app and status == 'Playing':
                        self.was_manually_paused = True
                        logger.log_info(f"检测到目标应用被手动暂停: {self.target_app_info.get('display_name')}")

                    await self.media_controller.control_media(source, 'pause' if status == 'Playing' else 'play')
                    # 请求强制刷新以立即更新UI
                    self.last_known_state = None
        except Exception: # queue.Empty
            pass


    async def _check_audio_and_control_target(self, audio_apps):
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
        
        # 检查目标应用是否仍然存在于最新的会话列表中
        latest_sessions = self.last_known_state or {}
        if target_source not in latest_sessions:
            self.ui_queue.put({'type': 'target_closed'})
            return

        if is_interfering:
            # 只有在目标正在播放时才暂停
            if latest_sessions.get(target_source, {}).get('status') == 'Playing' and not self.was_paused_by_app:
                logger.log_info(f"检测到干扰，正在暂停目标: {self.target_app_info.get('display_name')}")
                await self.media_controller.control_media(target_source, 'pause')
                self.ui_queue.put({'type': 'set_paused_flag', 'data': True})
        else:
            if self.was_paused_by_app:
                ignore_manual_pause = config_manager.get('general.ignore_manual_pause', False)
                
                # 如果开启了“手动暂停后不恢复”并且检测到了手动暂停，则不恢复
                if ignore_manual_pause and self.was_manually_paused:
                    logger.log_info(f"检测到手动暂停标志，根据设置不恢复播放: {self.target_app_info.get('display_name')}")
                    # 我们仍然需要重置 was_paused_by_app，否则下一次干扰也不会暂停它
                    self.ui_queue.put({'type': 'set_paused_flag', 'data': False})
                    return

                logger.log_info(f"干扰已消失，正在恢复目标: {self.target_app_info.get('display_name')}")
                await self.media_controller.control_media(target_source, 'play')
                self.ui_queue.put({'type': 'set_paused_flag', 'data': False})

    async def _update_media_sessions_list_async(self):
        """处理媒体会话列表的更新，由 sessions_changed 事件触发。"""
        try:
            media_sessions = await self.media_controller.get_media_sessions()
            
            with self.lock:
                audio_apps = self.latest_audio_apps_with_icons
            
            audio_app_details_by_pid = {app['pid']: app for app in audio_apps}
            enriched_sessions = []
            for session_info in media_sessions:
                display_name_lower = session_info['display_name'].lower()
                pid_map = {app['process_name'].lower().replace('.exe', ''): app['pid'] for app in audio_apps}
                pid = pid_map.get(display_name_lower)
                
                session_info['pid'] = pid
                session_info['icon'] = get_icon_for_pid(pid) if pid else None
                
                if pid and pid in audio_app_details_by_pid:
                    audio_details = audio_app_details_by_pid[pid]
                    session_info['process_name'] = audio_details.get('process_name')
                    session_info['peak_value'] = audio_details.get('peak_value')
                    session_info['display_name'] = audio_details.get('display_name', session_info['display_name'])

                enriched_sessions.append(session_info)

            current_state_for_ui = {s['source']: s for s in enriched_sessions}

            # --- 新增：检测目标应用的外部状态变化 ---
            if self.target_app_info and self.last_known_state:
                target_source = self.target_app_info['source']
                old_status = self.last_known_state.get(target_source, {}).get('status')
                new_status = current_state_for_ui.get(target_source, {}).get('status')

                # 如果应用从播放变为暂停，并且不是由本程序暂停的，则认为是手动暂停
                if old_status == 'Playing' and new_status == 'Paused' and not self.was_paused_by_app:
                    self.was_manually_paused = True
                    logger.log_info(f"检测到目标应用被外部暂停（可能为手动操作）: {self.target_app_info.get('display_name')}")

            if current_state_for_ui != self.last_known_state:
                self.ui_queue.put({'type': 'update_list', 'data': enriched_sessions})
                self.last_known_state = current_state_for_ui
        except Exception as e:
            logger.log_error(f"[后台工作线程] 更新媒体会话列表时出错: {e}")

    async def _periodic_check_loop_async(self):
        """周期性地检查所有应用的音频输出，并处理干扰逻辑。"""
        while not self.stop_event.is_set():
            try:
                await self._handle_worker_queue()

                # --- 核心改动：在主循环中也调用会话更新 ---
                await self._update_media_sessions_list_async()
                
                audio_apps = self.audio_monitor.get_audio_playing_apps()
                
                # --- 优化图标和应用缓存逻辑 ---
                with self.lock:
                    for app in audio_apps:
                        process_name = app.get('process_name')
                        if not process_name:
                            continue
                        
                        # 尝试从缓存恢复图标，因为 audio_monitor 不处理图标
                        cached_app = self.all_known_apps_cache.get(process_name)
                        if cached_app:
                            app['icon'] = cached_app.get('icon')
                        
                        # 如果仍然没有图标（对于新应用），则获取它
                        if not app.get('icon'):
                            app['icon'] = get_icon_for_pid(app['pid'])
                        
                        # 使用最新的应用信息（包括 is_playing 状态）更新缓存
                        self.all_known_apps_cache[process_name] = app

                    # 更新带有图标的最新应用列表
                    self.latest_audio_apps_with_icons = audio_apps

                self.ui_queue.put({'type': 'update_audio_apps', 'data': audio_apps})
                
                await self._check_audio_and_control_target(audio_apps)
                
                gc.collect()
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                logger.log_info("[后台工作线程] 周期性检查循环被取消。")
                break
            except Exception as e:
                logger.log_error(f"[后台工作线程] 周期性检查循环中发生错误: {e}")
                await asyncio.sleep(5)

    def run(self):
        logger.log_info("[COM] 正在初始化...")
        comtypes.CoInitialize()
        try:
            logger.log_info("[COM] 初始化成功。")
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            logger.log_info("[后台工作线程] 启动，切换到事件驱动模式")

            async def main_logic():
                self.async_stop_event = asyncio.Event()
                
                self.audio_monitor = AudioMonitor()
                self.media_controller = MediaController()
                try:
                    await self.media_controller.initialize()
                except Exception as e:
                    logger.log_error(f"MediaController 初始化失败: {e}")
                    return

                def on_sessions_changed(sender, args):
                    logger.log_debug("[事件] sessions_changed 事件触发")
                    if self.loop and not self.loop.is_closed():
                        asyncio.run_coroutine_threadsafe(self._update_media_sessions_list_async(), self.loop)

                event_token = self.media_controller.manager.add_sessions_changed(on_sessions_changed)
                
                periodic_task = self.loop.create_task(self._periodic_check_loop_async())

                logger.log_info("[后台工作线程] 周期性检查任务已启动，将自动加载会话列表。")
                
                await self.async_stop_event.wait()
                
                logger.log_info("[后台工作线程] 正在注销 sessions_changed 事件...")
                try:
                    self.media_controller.manager.remove_sessions_changed(event_token)
                except Exception as e:
                    logger.log_warning(f"注销 sessions_changed 事件时出错: {e}")
                
                periodic_task.cancel()
                await asyncio.gather(periodic_task, return_exceptions=True)

            self.loop.run_until_complete(main_logic())

        finally:
            logger.log_info("[后台工作线程] 开始关闭asyncio事件循环...")
            if self.loop and self.loop.is_running():
                tasks = asyncio.all_tasks(loop=self.loop)
                for task in tasks:
                    if not task.done():
                        task.cancel()
                group = asyncio.gather(*tasks, return_exceptions=True)
                self.loop.run_until_complete(group)
                self.loop.run_until_complete(self.loop.shutdown_asyncgens())
            
            if self.loop:
                self.loop.close()
            
            self.loop = None
            logger.log_info("[COM] 正在卸载...")
            comtypes.CoUninitialize()
            logger.log_info("[COM] 卸载成功。")
            logger.log_info("[后台工作线程] 事件循环已关闭，COM已卸载，线程停止运行。")