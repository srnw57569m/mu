from importlib import import_module
from highrise.__main__ import *
import time
import traceback
import psutil

# BOT SETTINGS #
bot_file_name = "musicbot"
bot_class_name = "MyBot"

from config import load_config, get_bot_token, get_room_id, ConfigError


def terminate_ffmpeg_processes():
    for proc in psutil.process_iter(['pid', 'name']):
        if 'ffmpeg' in proc.info['name']:
            try:
                proc.terminate()
                print(f"Terminated FFmpeg process: {proc.info['pid']}")
            except Exception as e:
                print(f"Failed to terminate process {proc.info['pid']}: {e}")

_cfg = load_config()
try:
    room_id = get_room_id(_cfg)
    bot_token = get_bot_token(_cfg)
except ConfigError as e:
    raise SystemExit(f"Failed to load required config values: {e}")

my_bot = BotDefinition(getattr(import_module(bot_file_name), bot_class_name)(), room_id, bot_token)


while True:
    try:
        # Cleanup lingering FFmpeg processes before restarting
        terminate_ffmpeg_processes()

        definitions = [my_bot]
        arun(main(definitions))
    except Exception as e:
        print(f"An exception occurred: {e}")
        traceback.print_exc()
        
        # Delay before reconnect attempt
        time.sleep(5)
