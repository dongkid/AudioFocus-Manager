import yaml
import os
from logger import logger

class ConfigManager:
    def __init__(self, config_path='config.yaml'):
        self.config_path = config_path
        self.defaults = {
            'general': {
                'always_on_top': False,
                'debug_mode': False
            },
            'logging': {
                'log_retention_days': 7
            },
            'audio': {
                'whitelist': {
                    "SystemSoundsService.exe": {"mode": "ignore"},
                    "audiodg.exe": {"mode": "ignore"}
                }
            }
        }
        self.config = self._load_config()

    def _load_config(self):
        """加载YAML配置文件。如果文件不存在，则创建并使用默认值。"""
        if not os.path.exists(self.config_path):
            logger.log_info(f"配置文件 '{self.config_path}' 不存在，将使用默认值创建。")
            self.config = self.defaults
            self.save_config()
            return self.defaults
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                user_config = yaml.safe_load(f)
                if not user_config:
                    logger.log_warning(f"配置文件 '{self.config_path}' 为空，将使用默认值。")
                    return self.defaults
                
                # 验证并合并配置
                validated_config = self._validate_config(user_config)
                return validated_config
        except Exception as e:
            logger.log_error(f"加载配置文件 '{self.config_path}' 时出错: {e}。将使用默认值。")
            return self.defaults

    def _validate_config(self, user_config):
        """验证用户配置，并与默认值合并。"""
        config = self.defaults.copy()
        
        # General settings
        if isinstance(user_config.get('general'), dict):
            general = user_config['general']
            if isinstance(general.get('always_on_top'), bool):
                config['general']['always_on_top'] = general['always_on_top']
            if isinstance(general.get('debug_mode'), bool):
                config['general']['debug_mode'] = general['debug_mode']
        
        # Logging settings
        if isinstance(user_config.get('logging'), dict):
            logging_conf = user_config['logging']
            if isinstance(logging_conf.get('log_retention_days'), int):
                days = logging_conf['log_retention_days']
                config['logging']['log_retention_days'] = max(1, min(days, 365)) # 限制在1-365天

        # Audio settings
        if isinstance(user_config.get('audio'), dict):
            audio_conf = user_config['audio']
            
            # --- 新的 whitelist 验证 ---
            if isinstance(audio_conf.get('whitelist'), dict):
                validated_whitelist = {}
                for app, settings in audio_conf['whitelist'].items():
                    if isinstance(settings, dict) and 'mode' in settings:
                        validated_whitelist[str(app)] = {
                            'mode': str(settings['mode']),
                            'delay_seconds': int(settings.get('delay_seconds', 2))
                        }
                config['audio']['whitelist'] = validated_whitelist

            # --- 向后兼容：迁移旧的 ignored_processes ---
            elif isinstance(audio_conf.get('ignored_processes'), list):
                logger.log_info("检测到旧的 'ignored_processes' 配置，正在迁移到新的 'whitelist' 结构。")
                # 先获取默认的白名单
                migrated_whitelist = config['audio']['whitelist'].copy()
                for process_name in audio_conf['ignored_processes']:
                    # 如果不在新的白名单里，就添加进去
                    if str(process_name) not in migrated_whitelist:
                        migrated_whitelist[str(process_name)] = {"mode": "ignore"}
                config['audio']['whitelist'] = migrated_whitelist

        return config

    def get(self, key, default=None):
        """获取配置项的值。"""
        keys = key.split('.')
        value = self.config
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default

    def set(self, key, value):
        """设置配置项的值。"""
        keys = key.split('.')
        d = self.config
        for k in keys[:-1]:
            d = d.setdefault(k, {})
        d[keys[-1]] = value

    def save_config(self):
        """将当前配置保存到YAML文件。"""
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(self.config, f, allow_unicode=True, default_flow_style=False)
            logger.log_info(f"配置已成功保存到 '{self.config_path}'。")
        except Exception as e:
            logger.log_error(f"保存配置文件 '{self.config_path}' 时出错: {e}")

    def reload_config(self):
        """从文件重新加载配置。"""
        logger.log_info("正在重新加载配置文件...")
        self.config = self._load_config()

# 创建一个全局实例，方便其他模块调用
config_manager = ConfigManager()