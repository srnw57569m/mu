# Standard library imports
import os
import subprocess
import time
import threading
import json
import random
import string
import glob
import re
import asyncio
from concurrent.futures import ThreadPoolExecutor

from config import (
    ConfigError,
    load_config,
    get_commands,
    get_messages,
    get_radio_settings,
    get_branding,
    build_alias_map,
) 


# Third-party imports
import yt_dlp
import yt_dlp as youtube_dl
from pytube import YouTube
from highrise import BaseBot, User, Position
from highrise.models import GetMessagesRequest
from typing import Any, Dict, Union, List

from highrise import BaseBot
from highrise.models import AnchorPosition, Item, Position, SessionMetadata, User, Reaction
from highrise import TaskGroup
from highrise import CurrencyItem
from highrise.models import Position, User
from typing import Literal, Union
from highrise import Highrise, GetMessagesRequest
from highrise import Highrise
import json
from highrise import BaseBot, SessionMetadata, User, Position
from highrise.webapi import *
from highrise.models_webapi import *
from highrise.models import *

PLAYLIST_FILE = "PLAYLIST_FILE.json"

class MyBot(BaseBot):
    def __init__(self):
        super().__init__()

        self._config = None
        self._commands_cfg = {}
        self._alias_map = {}
        self._messages = {}
        self._branding = {}
        self._radio = {}

        self._load_config_runtime()



        self.dance = None
        self.current_song = None
        self.song_queue = []
        self.pending_confirmations = {}
        self.currently_playing = False
        self.skip_event = asyncio.Event()
        self.skip_in_progress = False
        self.ffmpeg_process = None
        self.currently_playing_title = None
        self.credits = self.load_credits()  # Load credits from file
        self.admins = {'NXLN'}
        self.bot_pos = None
        self.ctoggle = False
        self.is_loading = True
        self.play_task = None
        self.play_event = asyncio.Event()
        self.skip_event = asyncio.Event()
        self.song_request_counts = self.load_stats()
        self.current_time = 0

        self.log_file = 'bot_log.json'
        self.logs, self.logging_enabled = self.load_logs()

        self.playlists = {}
        self.playlist_selector = {}

        self.nightcore = False
        self.daycore = False
        self.user_data = {}
        self.file_path = "user_data.json"  # File path for user data
        self.load_user_data()

        # keep config in sync with runtime state

    def _load_config_runtime(self) -> None:
        cfg = load_config()
        self._config = cfg
        self._radio = get_radio_settings(cfg)
        self._commands_cfg = get_commands(cfg)
        self._alias_map = build_alias_map(self._commands_cfg)
        self._messages = get_messages(cfg)
        self._branding = get_branding(cfg)

    def _msg(self, key: str, **kwargs: Any) -> str:
        template = self._messages.get(key, "")
        if not template:
            return ""
        return template.format(**kwargs)

    def _brand_footer(self) -> str:
        if not self._branding:
            return ""
        enabled = bool(self._branding.get("enabled", False))
        if not enabled:
            return ""
        footer = self._branding.get("footer", "")
        footer = str(footer).strip()
        if not footer:
            return ""
        return footer

    async def _chat(self, text: str) -> None:
        footer = self._brand_footer()
        if footer:
            text = f"{text}\n\n{footer}"
        await self.highrise.chat(text)

    async def _send_whisper(self, user_id: str, text: str) -> None:
        footer = self._brand_footer()
        if footer:
            text = f"{text}\n\n{footer}"
        await self.highrise.send_whisper(user_id, text)

    def _parse_command(self, message: str) -> tuple[str, str] | tuple[None, None]:
        prefix = (self._config or {}).get("bot", {}).get("command_prefix", "/")
        if not prefix:
            prefix = "/"
        # Only parse when it starts with prefix
        msg = message.strip()
        if not msg.startswith(prefix):
            return None, None
        after = msg[len(prefix):].strip()
        tokens = after.split()
        if not tokens:
            return None, None
        # multi-word candidate: first token or first two tokens
        first = tokens[0].lower()
        rest = after[len(tokens[0]):].lstrip() if len(after) > len(tokens[0]) else ""
        # try longest 2-token alias
        if len(tokens) >= 2:
            two = f"{tokens[0].lower()} {tokens[1].lower()}"
            if two in self._alias_map:
                canonical = self._alias_map[two]
                # rest after two tokens
                after_two = after[len(tokens[0]) + 1 + len(tokens[1]):].lstrip()
                return canonical, after_two
        if first in self._alias_map:
            canonical = self._alias_map[first]
            return canonical, rest
        return None, None

    def load_user_data(self):

        """Load user data from file."""
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r") as file:
                    self.user_data = json.load(file)
                print("User data loaded successfully.")
            except json.JSONDecodeError:
                print("Error: Failed to parse user data file.")
                self.user_data = {}
        else:
            print("User data file does not exist. Creating a new one.")
            self.user_data = {}

    def save_user_data(self):
        """Save user data to file."""
        try:
            with open(self.file_path, "w") as file:
                json.dump(self.user_data, file, indent=4)
            print("User data saved successfully.")
        except Exception as e:
            print(f"Error saving user data: {e}")

    async def on_tip(self, sender: User, receiver: User, tip: Union[CurrencyItem, Item]) -> None:
        """Handle tip events."""
        if receiver.username == "MANNAT_WATCHMEN" and isinstance(tip, CurrencyItem):
            user_id = sender.id
            user_name = sender.username
            tip_amount = tip.amount
            conversation_id = f"conversation_{user_id}"  # Generate conversation ID

            # Update user data
            if user_id not in self.user_data:
                self.user_data[user_id] = {
                    "username": user_name,
                    "conversation_id": conversation_id,
                    "balance": 0
                }

            # Add the tip amount to user's balance
            self.user_data[user_id]["balance"] += tip_amount
            self.save_user_data()

            # Send a thank-you message
            await self.highrise.send_whisper(
                user_id,
                f"Thank you for tipping {tip_amount}! Your balance has been updated."
            )

    async def on_start(self, session_metadata):
        print("nex is Armed and Ready.")
        self.is_loading = True

        if self.logging_enabled:
            self.logs += 1  # Increment logs count by 1
            self.save_logs()  # Save updated logs to the .json file

        self.queue = []
        self.load_playlists()
        self.currently_playing = False

        await self.highrise.chat("Initialization in progress. Please wait.")

        # Load location data and handle bot position
        self.load_loc_data()
        if self.bot_pos:
            await self.highrise.teleport(self.highrise.my_id, self.bot_pos)

        # Terminate any existing stream before restarting
        await self.stop_existing_stream()
        await asyncio.sleep(3)

        # Reset the skip event and clear any active playback
        self.skip_event.clear()
        self.load_queue()

        # Load the current song if there is one
        self.current_song = self.load_current_song()

        # Add the current song back to the queue as the first song
        if self.currently_playing_title:
            await self.highrise.chat(f"Replaying song due to disconnection: '{self.current_song['title']}'")
            self.song_queue.insert(0, self.current_song)  # Add it to the front of the queue
            await asyncio.sleep(5)

        # Terminate and recreate the playback loop
        if self.play_task and not self.play_task.done():
            print("Terminating the existing playback loop.")
            self.play_task.cancel()
            try:
                await self.play_task
            except asyncio.CancelledError:
                print("Existing playback loop terminated successfully.")

        print("Creating a new playback loop.")
        self.play_task = asyncio.create_task(self.playback_loop())

        # If there are songs in the queue, trigger the playback loop
        if self.song_queue:
            print("Songs found in queue. Triggering playback loop...")
            self.play_event.set()
        else:
            print("No songs found in queue. Playback loop will wait for new songs.")

        self.is_loading = False
        await self.highrise.chat("Initialization is complete.")

    async def on_chat(self, user: User, message: str) -> None:
        user_id = user.id

        if message.startswith('/sfx') and user.username in self.admins:

            if self.currently_playing:
                # Notify the user if a song is ongoing
                await self.highrise.send_whisper(user.id, f"@{user.username} You can't add an sfx while a song is playing.")
                return

            elif not self.currently_playing:

                command = message[5:].strip().lower()  # Get the part after '/sfx' and normalize to lowercase
                print(command)

                if command == "nightcore":
                    self.nightcore = True
                    self.daycore = False
                    await self.highrise.send_whisper(user.id, f"\n@{user.username} Nightcore effect selected.")
                    print("nightcore sfx enabled.")
                
                elif command == "daycore":
                    self.daycore = True
                    self.nightcore = False
                    await self.highrise.send_whisper(user.id, f"\n@{user.username} Daycore effect selected.")
                    print("daycore sfx enabled.")
                
                elif command == "normal":
                    self.nightcore = False
                    self.daycore = False
                    await self.highrise.send_whisper(user.id, f"\n@{user.username} Normal mode selected.")
                    print("all sfx removed.")
                
                else:
                    await self.highrise.send_whisper(user.id, f"\n@{user.username} Invalid effect. Use one of the following: nightcore, daycore, normal.")

                self.save_loc_data()
        if message.startswith('/np'):
            current_song = self.load_current_song()
            if current_song:
                song_title = current_song.get('title', 'Unknown')
                await self.highrise.chat(f"Now Playing: {song_title}\nEnjoy with us @{user.username}")
            else:
                await self.highrise.chat("No song is currently playing.")
        if message.startswith('/logstoggle') and user.username in self.admins:
            self.logging_enabled = not self.logging_enabled  # Toggle the logging state
            state = "enabled" if self.logging_enabled else "disabled"
            self.save_logs()  # Save the updated state to the .json file
            await self.highrise.chat(f"Logging has been {state}.")

        if message.startswith('/logsclear') and user.username in self.admins:
            self.logs = 0  # Clear the logs count
            self.save_logs()  # Save the cleared logs to the .json file
            await self.highrise.chat("Logs have been cleared.")

        if message.startswith('/top'):

            try:
                parts = message.split()
                # Check if a username is provided
                if len(parts) > 1 and parts[1].startswith('@'):
                    username = parts[1][1:]  # Remove the '@' to get the username

                    # Calculate the total requests and the top song for the user
                    user_total_requests = 0
                    user_top_song = None
                    user_top_song_count = 0

                    for song, data in self.song_request_counts.items():
                        # Check if the user has requested this song
                        if username in data["users"]:
                            user_total_requests += data["users"][username]
                            if data["users"][username] > user_top_song_count:
                                user_top_song = song
                                user_top_song_count = data["users"][username]

                    # Display stats for the user
                    if user_total_requests > 0:
                        user_top_song_user_count = self.song_request_counts[user_top_song]["users"].get(username, 0)

                        await self.highrise.chat(
    f"\n🎶 Status for [@{username}]:\n\n"
    f"✨ Total Song Requests: {user_total_requests}\n"
    f"🎵 Top Requested Song: '{user_top_song}'\n"
    f"🔁 Times Requested: {user_top_song_user_count}\n"
    f"📊 Total Request Count: {user_top_song_count}\n\n"
    f"🎧 Keep enjoying the music, [@{username}]! 🎶"
                        )
                    else:
                        await self.highrise.chat(f"Stats for [@{username}] are not available.")

                else:
                    # Extract page number from the message (default to 1 if not specified)
                    page_number = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1

                    if not self.song_request_counts:
                        await self.highrise.chat("The stats are empty.")
                        return

                    # Sort songs by request count
                    sorted_songs = sorted(self.song_request_counts.items(), key=lambda item: item[1]["count"], reverse=True)

                    # Limit to top 10 songs
                    sorted_songs = sorted_songs[:10]

                    # Paging logic
                    songs_per_page = 2
                    total_songs = len(sorted_songs)
                    total_pages = (total_songs + songs_per_page - 1) // songs_per_page

                    if page_number < 1 or page_number > total_pages:
                        await self.highrise.chat("Invalid page number.")
                        return

                    # Create the stat message for the current page
                    start_index = (page_number - 1) * songs_per_page
                    end_index = min(start_index + songs_per_page, total_songs)
                    stat_message = f"🎵 Top 10 Requested Songs (Page {page_number}/{total_pages}) 🎵\n\n"

                    # Iterate over the songs and add a blank line after every second song
                    song_count = 0
                    for i, (title, data) in enumerate(sorted_songs[start_index:end_index]):
                        stat_message += f"{start_index + i + 1}. {title} - {data['count']} request(s)\n"
                        song_count += 1

                    # Send the message
                    await self.highrise.chat(stat_message)

                    # Suggest the next page if there are more pages
                    if page_number < total_pages:
                        await self.highrise.chat(f"Use '/stat {page_number + 1}' to view the next page.")

            except Exception as e:
                # Handle any error that occurs
                await self.highrise.chat(f"An error occurred: {str(e)}")

        if message.startswith('/paid') and user.username in self.admins:
            parts = message.split()
    
            if len(parts) == 2:
                toggle_option = parts[1].lower()
        
                if toggle_option == "on":
                    self.ctoggle = True
                    await self.highrise.chat("\nCredits requirement has been enabled.")
                elif toggle_option == "off":
                    self.ctoggle = False
                    await self.highrise.chat("\nCredits requirement has been disabled.")
                else:
                    await self.highrise.chat("\nInvalid option. Use `/paid on` to enable or `/paid off` to disable.")
            else:
                await self.highrise.chat("\nUsage: `/paid on` to enable or `/paid off` to disable.")
    
            self.save_loc_data()

        if message.startswith("/refresh"):
            # Check if the user is in the admin list
            if user.username not in self.admins:
                return

            # Allow admins to crash the bot
            await self.highrise.chat("Refreshing the bot. Please wait.")
            await asyncio.sleep(5)

            # Terminate any active FFmpeg stream process before crashing
            if self.ffmpeg_process:
                self.ffmpeg_process.terminate()
                self.ffmpeg_process.wait()  # Ensure the process is completely stopped
                self.ffmpeg_process = None
                print("Terminated active stream process before crashing.")

            # Raise a RuntimeError to crash the bot intentionally
            raise RuntimeError("Intentional crash triggered by admin")
        
        if message.startswith("/shutdown"):
            # Check if the user is in the admin list
            if user.username not in self.admins:
                return
            
            if self.is_loading:
                await self.highrise.chat("The bot is still initializing. Please wait a moment before using the /shutdown command.")
                return

            # Allow admins to "crash" the bot
            await self.highrise.chat("Initializing shut down.")
            await asyncio.sleep(5)

            # Terminate any active FFmpeg stream process before shutting down
            if self.ffmpeg_process:
                self.ffmpeg_process.terminate()
                self.ffmpeg_process.wait()  # Ensure the process is completely stopped
                self.ffmpeg_process = None
                print("Terminated active stream process before shutting down.")

            # Clear the current song
            self.current_song = None
            self.save_current_song()

            # Optionally, close the bot connection (based on your bot's API/SDK)
            await self.highrise.chat("Shutting down.")
            await asyncio.sleep(2)

            os._exit(0)

        if message.startswith("/setpos") and user.username in self.admins:

            self.bot_pos = await self.get_actual_pos(user.id)
            await self.highrise.chat("Bot position set!")
            await asyncio.sleep(1)
            await self.highrise.teleport(self.highrise.my_id, self.bot_pos)
            await asyncio.sleep(1)
            await self.highrise.teleport(self.highrise.my_id, self.bot_pos)
            self.save_loc_data()

        if message.startswith('/admin ') and user.username in self.admins:

            parts = message.split()
            if len(parts) == 2:
                target_user = parts[1][1:]  # Remove '@' from the username
                if target_user not in self.admins:
                    self.admins.add(target_user)
                    await self.highrise.chat(f"@{target_user} has been added as an admin.")
                    self.save_loc_data()
                else:
                    await self.highrise.chat(f"@{target_user} is already an admin.")
            else:
                await self.highrise.chat("Usage: /admin @<username>")

        if message.startswith('/deladmin ') and user.username in self.admins:

            parts = message.split()
            if len(parts) == 2:
                target_user = parts[1][1:]  # Remove '@' from the username
                if target_user in self.admins:
                    self.admins.remove(target_user)
                    await self.highrise.chat(f"@{target_user} has been removed from the admin list.")
                    self.save_loc_data()
                else:
                    await self.highrise.chat(f"@{target_user} is not an admin.")
            else:
                await self.highrise.chat("Usage: /deladmin @<username>")

        if message.startswith('/cadmin') and user.username in self.admins:

            page_number = 1
            if len(message.split()) > 1:
                try:
                    page_number = int(message.split()[1])
                except ValueError:
                    await self.highrise.chat("Invalid page number.")
                    return
            await self.check_admins(page_number)

        # Credits logic
        if message.startswith('/ac '):
            if user.username not in self.admins:  # Only allow Xenoichi to add credits
                return
            
            parts = message.split()
            
            if len(parts) == 3:
                # Extract the username, ensuring it includes the '@' symbol
                target_user = parts[1]
                
                # Remove the '@' symbol if it's there
                if target_user.startswith('@'):
                    target_user = target_user[1:]
                else:
                    await self.highrise.chat("Invalid username format. Please include '@' before the username.")
                    return
                
                try:
                    amount = int(parts[2])
                    await self.add_credits(target_user, amount)
                except ValueError:
                    await self.highrise.chat("Invalid amount. Please provide a valid number for credits.")
            else:
                await self.highrise.chat("Usage: /ac @<username> <credits>")

        if message.startswith('/rc '):
            # Remove credits from a user
            if user.username not in self.admins:
                return
            
            parts = message.split()
            
            if len(parts) == 3:
                target_user = parts[1]
                
                # Remove the '@' symbol if it's there
                if target_user.startswith('@'):
                    target_user = target_user[1:]
                else:
                    await self.highrise.chat("Invalid username format. Please include '@' before the username.")
                    return
                
                try:
                    amount = int(parts[2])
                    await self.remove_credits(target_user, amount)
                except ValueError:
                    await self.highrise.chat("Invalid amount. Please provide a valid number for credits.")
            else:
                await self.highrise.chat("Usage: /rc @<username> <credits>")

        if message.startswith('/cc'):
            await self.check_credits(user.username)

        if message.startswith('/cac'):

            if user.username not in self.admins:
                return
    
            parts = message.split()

            if len(parts) == 1:
                # No confirmation code provided, generate a new one
                if user.username in self.pending_confirmations:
                    confirmation_code = self.pending_confirmations[user.username]
                    await self.highrise.chat(f"You already have a pending confirmation.\n\n Type '/cac {confirmation_code}' to confirm.")
                    return

                # Generate a new random 5-letter confirmation code
                confirmation_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
                self.pending_confirmations[user.username] = confirmation_code
                await self.highrise.chat(f"Are you sure you want to clear all credits?\n\n Type '/cac {confirmation_code}' to confirm.")

            elif len(parts) == 2:
                # A confirmation code was provided
                confirmation_code = self.pending_confirmations.get(user.username)

                if confirmation_code:
                    provided_code = parts[1]
                    if provided_code == confirmation_code:
                        await self.clear_all_credits()
                        del self.pending_confirmations[user.username]
                    else:
                        await self.highrise.chat("Invalid confirmation code. Please check and try again.")
                else:
                    await self.highrise.chat("You have no pending actions to confirm.")
        if message.startswith('/p '):

            content = message[6:].strip()
            print(f"{user.username}: /p {content}")

            if content.startswith('[') and content.endswith(']'):
                # Extract the playlist name from inside the brackets
                playlist_name = content[1:-1].strip()

                if playlist_name:  # Ensure the playlist name is not empty
                    await self.play_playlist(playlist_name, user)
                else:
                    await self.highrise.chat("Please provide a valid playlist name inside the brackets. Use '/play [playlist_name]'.")
                return

            if self.is_loading:
                await self.highrise.chat("The bot is still initializing. Please wait a moment before using the /play command.")
            
            song_request = message[len('/p '):].strip()

            await self.highrise.send_whisper(user_id,f"\n🔎 Searching @{user.username} \nPowered by Beatly.")

            # Fetch video details using yt_dlp search
            title, duration, file_path, info = await self.search_youtube(song_request, user)

            if not info:
                await self.highrise.send_whisper(user_id,f"\n[@{user.username}], I couldn't retrieve details for your song request. Please try a different keyword(s) or URL.")
                return

            # Validate title, duration, and file path
            if not title or duration is None or file_path is None:
                await self.highrise.send_whisper(user_id,f"\n[@{user.username}], I couldn't retrieve details for your song request. Please try a different keyword(s) or URL.")
                return

            # Check if the song passed the duration limit
            if duration > 12 * 60:  # 12 minutes limit
                await self.highrise.send_whisper(user_id,f"\n[@{user.username}], your song: '{title}' exceeds the 12-minute duration limit and cannot be added.")
                return

            print("search_youtube function done.")

            if self.ctoggle:
                # Get the user's current credits from self.credits
                user_credits = self.credits.get(user.username, 0)  # Default to 0 if the user is not found
                
                if user_credits <= 0:
                    await self.highrise.send_whisper(user_id,f"\n[@{user.username}], you need at least 1 credit to queue a song.")
                    return
                
            await self.add_to_queue(user.username, title, duration, file_path,self.ctoggle)
        if message.startswith('/play '):

            content = message[6:].strip()
            print(f"{user.username}: /play {content}")

            if content.startswith('[') and content.endswith(']'):
                # Extract the playlist name from inside the brackets
                playlist_name = content[1:-1].strip()

                if playlist_name:  # Ensure the playlist name is not empty
                    await self.play_playlist(playlist_name, user)
                else:
                    await self.highrise.send_whisper(user_id,"Please provide a valid playlist name inside the brackets. Use '/play [playlist_name]'.")
                return

            if self.is_loading:
                await self.highrise.send_whisper(user_id,"The bot is still initializing. Please wait a moment before using the /play command.")
            
            song_request = message[len('/play '):].strip()

            await self.highrise.send_whisper(user_id,f"\n🔎 Searching @{user.username} \nPowered by Beatly.")

            # Fetch video details using yt_dlp search
            title, duration, file_path, info = await self.search_youtube(song_request, user)

            if not info:
                await self.highrise.send_whisper(user_id,f"\n[@{user.username}], I couldn't retrieve details for your song request. Please try a different keyword(s) or URL.")
                return

            # Validate title, duration, and file path
            if not title or duration is None or file_path is None:
                await self.highrise.send_whisper(user_id,f"\n[@{user.username}], I couldn't retrieve details for your song request. Please try a different keyword(s) or URL.")
                return

            # Check if the song passed the duration limit
            if duration > 12 * 60:  # 12 minutes limit
                await self.highrise.send_whisper(user_id,f"\n[@{user.username}], your song: '{title}' exceeds the 12-minute duration limit and cannot be added.")
                return

            print("search_youtube function done.")

            if self.ctoggle:
                # Get the user's current credits from self.credits
                user_credits = self.credits.get(user.username, 0)  # Default to 0 if the user is not found
                
                if user_credits <= 0:
                    await self.highrise.send_whisper(user_id,f"\n[@{user.username}], you need at least 1 credit to queue a song.")
                    return
                
            await self.add_to_queue(user.username, title, duration, file_path,self.ctoggle)

        if message.startswith('/skip') and user.username in self.admins:
            await self.skip_song(user)  # Pass user.username to the skip_song method
        if message.startswith('/s') and user.username in self.admins:
            await self.skip_song(user)  # Pass user.username to the skip_song method
        if message.startswith('/delq'):

            parts = message.split()

            if len(parts) == 1:
                # Call the del_last_song function to delete the user's last song
                await self.del_last_song(user.username)

        if message.startswith('/clearq') and user.username in self.admins:

            parts = message.split()

            if len(parts) == 1:
                # Call the clear_queue function to remove all songs from the user's queue and delete the files
                await self.clear_queue()

        if message.startswith('/q'):

            page_number = 1
            try:
                page_number = int(message.split(' ')[1])
            except (IndexError, ValueError):
                pass
            await self.check_queue(page_number)

        if message.startswith('/np'):
            await self.now_playing()
        if message.strip() == "/bal":
            if user_id in self.user_data:
                balance = self.user_data[user_id]["balance"]
                await self.highrise.send_whisper(
                    user_id,
                    f"Your current balance is {balance}."
                )
            else:
                await self.highrise.send_whisper(
                    user_id,
                    "You don't have a balance yet. Tip the bot to get started!"
                )

        elif message.startswith("/buy"):
            parts = message.split()
            if len(parts) >= 2:
                try:
                    amount = int(parts[1])  # Get the amount from message

                    # Check if the user has enough balance
                    if user_id in self.user_data:
                        user_balance = self.user_data[user_id]["balance"]

                        if user_balance >= amount:
                            # Deduct the amount and add to credits
                            self.user_data[user_id]["balance"] -= amount
                            self.save_user_data()

                            # Add credits to the user
                            await self.add_credits(user.username, amount)

                            # Send a success message
                            await self.highrise.send_whisper(
                                user_id,
                                f"Successfully bought {amount} song(s)! Your new balance is {self.user_data[user_id]['balance']}."
                            )
                        else:
                            # Insufficient balance
                            await self.highrise.send_whisper(
                                user_id,
                                "You don't have enough balance to buy the song. Check your balance using `!bal`."
                            )
                    else:
                        await self.highrise.send_whisper(
                            user_id,
                            "You don't have a balance yet. Tip the bot to get started!"
                        )

                except ValueError:
                    await self.highrise.send_whisper(
                        user_id,
                        "Invalid amount. Please enter a valid number for the song(s) to buy."
                    )
            else:
                await self.highrise.send_whisper(
                    user_id,
                    "Usage: /buy <amount> song(s). Example: /buy 10 song"
                )
            

    async def on_message(self, user_id: str, conversation_id: str, is_new_conversation: bool) -> None:
        # Fetch the latest message in the conversation
        response = await self.highrise.get_messages(conversation_id)
        if isinstance(response, GetMessagesRequest.GetMessagesResponse):
            message = response.messages[0].content  # Get the message content

        # Get the username based on user_id
        username = await self.get_user_details(user_id)
        print(f"{username} {message}")
        
        # Handle /pl create command
        if message.startswith('!create ') and username in self.admins:
            playlist_name = message[len('!create '):].strip()

            # Check if the total number of playlists exceeds the limit (20)
            if len(self.playlists) >= 20:
                await self.highrise.send_message(conversation_id, "Cannot create playlist. Maximum limit of 20 playlists reached.")
                return

            if playlist_name in self.playlists:
                await self.highrise.send_message(conversation_id, f"Playlist '{playlist_name}' already exists.")
            else:
                # Store the playlist with the creator's username
                self.playlists[playlist_name] = {
                    "songs": [],  # List to store songs
                    "created_by": username  # Store the username of the creator
                }

                await self.highrise.send_message(conversation_id, f"Playlist '{playlist_name}' has been created.")
                self.save_playlists()

        if message.startswith('!rename ') and username in self.admins:
            try:
                parts = message.split(maxsplit=1)
                if len(parts) == 2:
                    new_playlist_name = parts[1].strip()
                    playlist_name = self.playlist_selector.get(username)

                    if not playlist_name:
                        await self.highrise.send_message(conversation_id, "You haven't selected a playlist.")
                        return

                    if playlist_name in self.playlists:
                        # Update the playlist name
                        self.playlists[new_playlist_name] = self.playlists.pop(playlist_name)
                        self.save_playlists()
                        self.playlist_selector[username] = new_playlist_name  # Update selected playlist
                        await self.highrise.send_message(conversation_id, f"Playlist has been renamed to '{new_playlist_name}'.")
                    else:
                        await self.highrise.send_message(conversation_id, f"Playlist '{playlist_name}' does not exist.")
                else:
                    await self.highrise.send_message(conversation_id, "Please specify the new name for the playlist.")
            except Exception as e:
                await self.highrise.send_message(conversation_id, "An error occurred while renaming the playlist.")
                print(f"Error: {e}")

        if message.startswith('!select ') and username in self.admins:
            parts = message.split(maxsplit=1)
            if len(parts) == 2:
                playlist_name = parts[1].strip()
                if playlist_name in self.playlists:
                    self.playlist_selector[username] = playlist_name
                    await self.highrise.send_message(conversation_id, f"Playlist '{playlist_name}' has been selected.")
                else:
                    await self.highrise.send_message(conversation_id, f"Playlist '{playlist_name}' does not exist.")
            else:
                await self.highrise.send_message(conversation_id, "Please specify a playlist name to select.")

        if message.startswith('!add ') and username in self.admins:
            try:

                # Check if the user has a selected playlist
                if username not in self.playlist_selector:
                    await self.highrise.send_message(conversation_id, "You haven't selected a playlist. Use '!select [name of playlist]' to select one.")
                    return

                # Retrieve the selected playlist name
                playlist_name = self.playlist_selector[username]
                song_query = message[len('!add '):].strip()

                # Add the song to the selected playlist
                if playlist_name not in self.playlists:
                    await self.highrise.send_message(conversation_id, f"Playlist '{playlist_name}' no longer exists.")
                    return
                
                # Check if the playlist already has 20 songs
                if len(self.playlists[playlist_name]["songs"]) >= 20:
                    await self.highrise.send_message(conversation_id, f"Playlist '{playlist_name}' is full. You cannot add more.")
                    return

                await self.highrise.send_message(conversation_id, "🔎 Search in progress.")

                await self.add_song_to_playlist(conversation_id, playlist_name, song_query, username)

            except Exception as e:
                await self.highrise.send_message(conversation_id, "An error occurred while adding the song.")
                print(f"Error: {e}")

        if message.startswith('!list') and username in self.admins:
            # No need to handle paging anymore
            playlists_message = "Playlists:\n\n"

            # Check if there are any playlists
            if not self.playlists:
                await self.highrise.send_message(conversation_id, "There are no playlists available.")
                return

            # Loop through all playlists with an index
            for index, (playlist_name, details) in enumerate(self.playlists.items(), start=1):
                creator = details["created_by"]
                song_count = len(details["songs"])  # Number of songs in the playlist
                playlists_message += (
                    f"{index}.\n"
                    f"{playlist_name}\n"
                    f"Created by: @{creator}\n"
                    f"Number of Songs: {song_count}\n"
                    f"\n"
                )

            # Send the list of all playlists
            await self.highrise.send_message(conversation_id, playlists_message)

        if message.startswith('!delete') and username in self.admins:
            try:
                # Check if the user has selected a playlist
                if username in self.playlist_selector:
                    playlist_name = self.playlist_selector[username]

                    # Check if the playlist exists
                    if playlist_name in self.playlists:
                        # Delete the selected playlist
                        del self.playlists[playlist_name]
                        del self.playlist_selector[username]  # Remove the selected playlist for the user
                        self.save_playlists()
                        await self.highrise.send_message(conversation_id, f"Selected playlist '{playlist_name}' has been deleted.")
                    else:
                        await self.highrise.send_message(conversation_id, f"Playlist '{playlist_name}' does not exist.")
                else:
                    await self.highrise.send_message(conversation_id, "You haven't selected a playlist to delete.")
            except Exception as e:
                await self.highrise.send_message(conversation_id, "An error occurred while deleting the playlist.")
                print(f"Error: {e}")

        if message.startswith('!remove ') and username in self.admins:
            try:
                parts = message.split(maxsplit=1)
                if len(parts) == 2:
                    song_position = int(parts[1].strip())
                    playlist_name = self.playlist_selector.get(username)

                    if not playlist_name:
                        await self.highrise.send_message(conversation_id, "You haven't selected a playlist.")
                        return

                    # Check if the playlist exists and has songs
                    if playlist_name in self.playlists and "songs" in self.playlists[playlist_name]:
                        songs = self.playlists[playlist_name]["songs"]

                        # Validate the song position
                        if 1 <= song_position <= len(songs):
                            removed_song = songs.pop(song_position - 1)  # 1-based to 0-based index
                            self.save_playlists()
                            await self.highrise.send_message(conversation_id, f"Song '{removed_song['title']}' has been removed from the playlist.")
                        else:
                            await self.highrise.send_message(conversation_id, f"Invalid song position.")
                    else:
                        await self.highrise.send_message(conversation_id, f"Playlist '{playlist_name}' not found or no songs in the playlist.")
                else:
                    await self.highrise.send_message(conversation_id, "Please specify the song position to remove.")
            except ValueError:
                await self.highrise.send_message(conversation_id, "Please provide a valid song position.")
            except Exception as e:
                await self.highrise.send_message(conversation_id, "An error occurred while removing the song.")
                print(f"Error: {e}")

        if message.startswith('!shuffle') and username in self.admins:
            try:
                playlist_name = self.playlist_selector.get(username)

                if not playlist_name:
                    await self.highrise.send_message(conversation_id, "You haven't selected a playlist.")
                    return

                if playlist_name in self.playlists:
                    songs = self.playlists[playlist_name]["songs"]
                    random.shuffle(songs)  # Shuffle the list of songs
                    self.save_playlists()
                    await self.highrise.send_message(conversation_id, f"Playlist '{playlist_name}' has been shuffled.")
                else:
                    await self.highrise.send_message(conversation_id, f"Playlist '{playlist_name}' does not exist.")
            except Exception as e:
                await self.highrise.send_message(conversation_id, "An error occurred while shuffling the playlist.")
                print(f"Error: {e}")

        if message.startswith('!view') and username in self.admins:
            parts = message.split(maxsplit=1)

            if len(parts) == 2:  # If a playlist name is provided
                playlist_name = parts[1].strip()
            else:  # Use the selected playlist for the user
                playlist_name = self.playlist_selector.get(username)

            if not playlist_name:
                await self.highrise.send_message(conversation_id, "No playlist selected. Use '!select <playlist_name>' to choose a playlist.")
                return

            # View the songs in the playlist
            await self.view_playlist_songs(conversation_id, playlist_name)

        if message.startswith('!help'):
            help_message = """
🎵 **Playlist Creation Guide** 🎵

Admin(s) only:

1. !create [playlist_name]  
- Create a new playlist.  
- Example: `!create MyFavorites`
- You can have a maximum of 20 playlists at a time.

2. !select [playlist_name]
- Select an existing playlist to manage.
- Example: `!select MyFavorites`
- Once selected, the playlist becomes your active playlist for adding and removing songs.

3. !delete
- Delete the currently selected playlist.  
- Make sure you select a playlist first using `!select [playlist_name]`.

4. !rename [new_playlist_name]
- Rename the currently selected playlist.  
- Example: `!rename MyNewFavorites`
- Ensure you've selected a playlist using `!select [playlist_name]` before renaming.

5. !list
- View all available playlists, along with their song count and creator details.

6. !add [song_name]
- Add a song to the currently selected playlist.
- Example: `!add Let Her Go`
- Only a maximum of 20 songs can be added to a playlist.

7. !remove [song_position]
- Remove a song from the currently selected playlist based on its position.
- Example: `!remove 2` will remove the second song in the playlist.

8. !view
- View the songs the in the currently selected playlist.  

9. !shuffle  
- Shuffle the songs in the currently selected playlist.

10. /play [playlist_name]
- Use this command to add your playlist to the queue.
- The name of the playlist must be inside the brackets.
- Example: `/play [MyFavorites]`
- IMPORTANT: This command must be executed outside of DM.
    """
            await self.highrise.send_message(conversation_id, help_message)


    async def check_admins(self, page_number=1):
        admins_per_page = 5  # How many admins per page
        admins_list = list(self.admins)
        total_pages = (len(admins_list) // admins_per_page) + (1 if len(admins_list) % admins_per_page != 0 else 0)
        
        if page_number > total_pages:
            await self.highrise.chat(f"Page {page_number} does not exist. Only {total_pages} pages of admins.")
            return

        start_index = (page_number - 1) * admins_per_page
        end_index = min(start_index + admins_per_page, len(admins_list))
        admins_page = admins_list[start_index:end_index]
        
        # Display the admins on this page with numbers instead of '@'
        admins_message = f"Page {page_number}/{total_pages}:\nAdmins:\n"
        admins_message += "\n".join([f"{index + 1}. {admin}" for index, admin in enumerate(admins_page)])
        await self.highrise.chat(admins_message)

    async def add_credits(self, username, amount):
        """Adds credits to a user."""
        self.credits[username] = self.credits.get(username, 0) + amount
        await self.save_credits()
        await self.highrise.chat(f"Added {amount} credits to @{username}.\n\nCurrent balance: {self.credits[username]}")

    async def remove_credits(self, username, amount):
        if username in self.credits:
            self.credits[username] -= amount
            if self.credits[username] < 0:
                self.credits[username] = 0
            await self.save_credits()
            await self.highrise.chat(f"Removed {amount} credits from @{username}.\n\nRemaining balance: {self.credits[username]}")
        else:
            await self.highrise.chat(f"@{username} does not have any credits.")

    async def check_credits(self, username):
        """Checks the credits of a user."""
        current_credits = self.credits.get(username, 0)
        await self.save_credits()
        await self.highrise.chat(f"@{username}, you have {current_credits} credits.")

    async def clear_all_credits(self):
        self.credits = {}
        await self.highrise.chat("All user credits have been cleared.")

    async def has_enough_credits(self, username):
        """Checks if a user has enough credits to request a song."""
        return self.credits.get(username, 0) > 0

    async def deduct_credit(self, username):
        """Deducts 1 credit from a user's balance."""
        if username in self.credits and self.credits[username] > 0:
            self.credits[username] -= 1
            await self.save_credits()
            print(f"Credit deducted for {username}. Remaining credits: {self.credits[username]}")

    def load_credits(self):
        """Loads the credits from a file."""
        try:
            with open('credits.json', 'r') as file:
                return json.load(file)
        except FileNotFoundError:
            return {}

    async def save_credits(self):
        """Saves the credits to a file."""
        with open('credits.json', 'w') as file:
            json.dump(self.credits, file)

    async def check_queue(self, page_number=1):

        try:

            songs_per_page = 2
            total_songs = len(self.song_queue)
            total_pages = (total_songs + songs_per_page - 1) // songs_per_page

            if total_songs == 0:
                await self.highrise.chat("The queue is currently empty.")
                return

            if page_number < 1 or page_number > total_pages:
                await self.highrise.chat("Invalid page number.")
                return

            queue_message = f"There's {total_songs} song(s) in the queue (Page {page_number}/{total_pages}):\n\n"
            start_index = (page_number - 1) * songs_per_page
            end_index = min(start_index + songs_per_page, total_songs)

            for index, song in enumerate(self.song_queue[start_index:end_index], start=start_index + 1):

                # Get the duration, default to 0 if not available
                duration = song.get('duration', 0)

                # Format the duration as MM:SS
                duration_minutes = int(duration // 60)
                duration_seconds = int(duration % 60)
                formatted_duration = f"{duration_minutes}:{duration_seconds:02d}"

                queue_message += f"{index}. '{song['title']}' ({formatted_duration}) req by @{song['owner']}\n"

            await self.highrise.chat(queue_message)

            if page_number < total_pages:
                await self.highrise.chat(f"Use '/q {page_number + 1}' to view the next page.")

        except Exception as e:
            # Handle any error that occurs
            await self.highrise.chat(f"An error occurred: {str(e)}")


    async def add_to_queue(self, owner, title, duration, file_path, ctoggle_state):

        # Check if the user has already queued 3 songs
        user_song_count = 0

        # Check the current song owner (if it's not None)
        if self.current_song and self.current_song.get('owner') == owner:
            user_song_count += 1

        # Check the songs in the queue
        for song in self.song_queue:
            if song.get('owner') == owner:
                user_song_count += 1

        # If the user has 3 songs, prevent adding another song to the queue
        if user_song_count >= 3:
            await self.highrise.chat(f"\n[@{owner}], you can only queue up to 3 songs. Please wait until one finishes.")
            return
    
        if file_path and title and duration:

            # If not in the queue, add the song
            self.song_queue.append({
                'title': title,
                'file_path': file_path,
                'owner': owner,
                'duration': duration,
                'ctoggle_enabled': ctoggle_state 
            })

            # Save the queue after adding a song
            self.save_queue()

            self.update_song_request_stats(title, owner)
            print("update_song_request_stats function done.")

            duration_minutes = int(duration // 60)
            duration_seconds = int(duration % 60)
            formatted_duration = f"{duration_minutes}:{duration_seconds:02d}"

            # Get the queue position
            queue_position = len(self.song_queue)

            await self.highrise.chat(
    f"\nNew song added to the queue!\n"
    f"Title: {title}\n"
    f"Duration: {formatted_duration}\n"
    f"Requested By: @{owner}\n\n"
    f"Queue Position: #{queue_position}\n\n"
    f"Stay Tuned, It's Coming Up Next! "
            )

            if self.ctoggle:
                try:
                    self.credits[owner] -= 1  # Deduct 1 credit
                except Exception as e:
                    print(f"Failed to send whisper to {owner}: {e}")
                finally:
                    await self.save_credits()  # Save the credits to the file

            if not self.play_task or self.play_task.done():
                print("Playback loop has been created.")
                self.play_task = asyncio.create_task(self.playback_loop())

            self.play_event.set()
            print("add_to_queue function done.")
            
    async def del_last_song(self, owner):
    # Find the last song that the user added to the queue
        last_song = None
        for song in reversed(self.song_queue):
            if song['owner'] == owner:
                last_song = song
                break

        if last_song:
        # Remove the last song from the queue
            self.song_queue.remove(last_song)

        # Refund credit only if ctoggle was enabled when the song was added
            if last_song.get('ctoggle_enabled', False):  # Check if ctoggle was enabled
                if owner in self.credits:
                    self.credits[owner] = self.credits.get(owner, 0) + 1  # Refund 1 credit
                    await self.save_credits()  # Save updated credits to file
                await self.highrise.chat(
                f"[@{owner}], your last song: '{last_song['title']}' has been removed from the queue.\n"
                f"💰 1 credit has been refunded to your account."
            )
            else:
                await self.highrise.chat(
                f"[@{owner}], your last song: '{last_song['title']}' has been removed from the queue."
            )

        # Save the updated queue
            self.save_queue()
        else:
            await self.highrise.chat(f"[@{owner}], you have no songs in the queue to remove.")

    async def clear_queue(self):
        """Clears all songs from the queue and deletes all downloaded files."""

        # Clear the song queue
        self.song_queue.clear()

        # Delete all downloaded files in the 'downloads' folder
        downloaded_files = glob.glob('downloads/*')  # This will match all files in the 'downloads' folder
        for file in downloaded_files:
            try:
                os.remove(file)  # Remove the file
                print(f"Deleted file: {file}")
            except Exception as e:
                print(f"Error deleting file {file}: {e}")

        # Optionally, save the empty queue and reset other states as needed
        self.save_queue()

        # Notify the admin that the queue has been cleared and files deleted
        await self.highrise.chat("All songs have been cleared from the queue.")

    async def now_playing(self):
        if self.current_song is None:
            await self.highrise.chat("No song is currently playing.")
            return

        if self.currently_playing_title:
            current_song = self.current_song
            total_duration = current_song.get('duration', 0)

            # Fetch real-time elapsed duration from FFmpeg log
            elapsed_time = self.current_time

            # Ensure elapsed_time doesn't exceed the total duration
            elapsed_time = min(elapsed_time, total_duration)

            # Calculate progress
            progress_percentage = (elapsed_time / total_duration) * 100
            progress_bar_length = 10
            filled_length = int(progress_percentage / (100 / progress_bar_length))
            progress_bar = '━' * filled_length
            empty_bar = '─' * (progress_bar_length - filled_length)
            progress_bar_display = f"{progress_bar}⬤{empty_bar}"

            # Format time as MM:SS
            total_duration_str = f"{int(total_duration // 60)}:{int(total_duration % 60):02d}"
            elapsed_time_str = f"{int(elapsed_time // 60)}:{int(elapsed_time % 60):02d}"

            await self.highrise.chat(
                f"\nNow Playing: '{self.currently_playing_title}'\n\n"
                f"{elapsed_time_str} {progress_bar_display} {total_duration_str}\n\n"
                f"Requested by [@{current_song['owner']}]"
            )
        else:
            await self.highrise.chat("No song is currently playing.")

    async def playback_loop(self):
        while True:
            await self.play_event.wait()

            while self.song_queue:
                if self.skip_event.is_set():
                    self.skip_event.clear()
                    # Skip the current song and move on to the next song
                    print("Song skipped due to skip_event being set")
                    self.currently_playing = False
                    self.currently_playing_title = None
                    continue

                if not self.song_queue:
                    break

                next_song = self.song_queue.pop(0)
                self.save_queue()
                self.current_song = next_song
                self.save_current_song()
                self.currently_playing = True
                self.currently_playing_title = next_song['title']

                song_title = next_song['title']
                song_owner = next_song['owner']

                self.song_start_time = time.time()
                duration = next_song.get('duration', 0)
                formatted_duration = f"{int(duration // 60)}:{int(duration % 60):02d}"

                # Convert and stream the song
                song_file_path = await self.download_youtube_audio(song_title)

                await self.highrise.chat(
                    f"Next Song: '{song_title}' ({formatted_duration})\n\nRequested by  @{song_owner}\n\nPowered by Beatly."
                )

                print(f"Playing: {song_title}")

                if not isinstance(song_file_path, str) or not song_file_path or not os.path.exists(song_file_path) or os.path.getsize(song_file_path) <= 0:
                    await self.highrise.chat("There was a problem downloading the song. Skipping to the next one.")
                    self.currently_playing = False
                    self.currently_playing_title = None
                    continue


                # Stream the song
                await self.stream_to_radioking(song_file_path)

                if self.skip_event.is_set():
                    self.skip_event.clear()
                    break  # Skip the current song and move on to the next song

                # Clean up files after streaming
                if os.path.exists(song_file_path):
                    os.remove(song_file_path)

                self.currently_playing = False
                self.current_song = None

                await asyncio.sleep(10)

            if not self.song_queue:
                self.play_event.clear()
                await self.highrise.chat("The queue is now empty.")

            self.currently_playing = False
            self.currently_playing_title = None

    async def stream_to_radioking(self, song_file_path):
        radio = self._radio or get_radio_settings(self._config or load_config())
        icecast_server = radio.get("icecast_server")
        icecast_port = radio.get("icecast_port")
        mount_point = radio.get("mount_point")
        username = radio.get("username")
        password = radio.get("password")

        icecast_url = f"icecast://{username}:{password}@{icecast_server}:{icecast_port}{mount_point}"

        with ThreadPoolExecutor() as executor:

            # Use the `_run_ffmpeg` helper inside the executor
            future = executor.submit(self._run_ffmpeg, song_file_path, icecast_url)
            await asyncio.get_event_loop().run_in_executor(None, future.result)

    def _run_ffmpeg(self, song_file_path, icecast_url):


        # Analyze the volume first
        mean_volume = self.analyze_volume(song_file_path)
        print(f"Detected mean volume: {mean_volume} dB")

        # Set volume adjustment if needed
        volume_adjustment = None
        if mean_volume is not None and mean_volume < -5.0:  # Example threshold
            volume_adjustment = f"volume={-mean_volume:.1f}dB"  # Normalize to 0 dB
            print(f"ADJUSTING VOLUME")

        # Temporary MP3 file path
        encoded_mp3_path = "encoded_song.mp3"

        # Step 1: Encode the audio file to MP3
        encode_command = [
            'ffmpeg', 
            '-y',              # Overwrite output file without asking
            '-i', song_file_path,  # Input audio file
            '-f', 'mp3',       # Specify output format as MP3
            '-acodec', 'libmp3lame',  # Use the libmp3lame codec for MP3 encoding
            '-b:a', '256k',     # Set bitrate to 128kbps (less CPU intensive, lower quality)
            '-ar', '44100',     # Set sample rate to 44100Hz
            '-ac', '2',         # Stereo channels
            '-qscale:a', '8',   # Adjust quality scale for a balance between speed and quality (lower = better quality)
            encoded_mp3_path    # Output MP3 file
        ]

        # Apply daycore effect if active
        if self.daycore:
            encode_command.insert(4, '-filter_complex')
            encode_command.insert(5, 'asetrate=44100*0.85,aresample=44100,atempo=1.176,equalizer=f=1000:t=q:w=1:g=5,equalizer=f=5000:t=q:w=1:g=10')

        # Apply nightcore effect if active
        if self.nightcore:  # `elif` ensures only one effect is applied
            encode_command.insert(4, '-filter_complex')
            encode_command.insert(5, 'asetrate=48000*1.15,aresample=48000,atempo=1.15,dynaudnorm')

        # Add the volume filter if adjustment is needed
        if volume_adjustment:
            encode_command.extend(['-af', volume_adjustment])

        def log_ffmpeg_progress(ffmpeg_process):

            last_logged_time = -1  # Initialize last logged time to prevent duplicate logs

            while True:
                line = ffmpeg_process.stderr.readline().strip()
                if not line:
                    break  # Exit the loop if no more data is available

                # Match the time information from FFmpeg output
                match = re.search(r"time=(\d{2}):(\d{2}):(\d{2})\.(\d+)", line)
                if match:
                    hours, minutes, seconds, _ = map(int, match.groups())
                    current_time = hours * 3600 + minutes * 60 + seconds

                    # Start logging from the beginning without any delay
                    if current_time != last_logged_time:
                        self.current_time = current_time  # Update the elapsed time
                        print(f"Streaming: {self.current_time + 1} seconds elapsed")
                        last_logged_time = current_time

        try:
            
            # Step 1: Encode the song to MP3
            encode_process = subprocess.Popen(
                encode_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1
            )

            # Start a thread to process FFmpeg stderr for encoding progress
            print("ENCODING STARTED")
            threading.Thread(target=log_ffmpeg_progress, args=(encode_process,), daemon=True).start()

            # Wait for encoding to complete
            encode_process.wait()
            print("ENCODING DONE : ✅")

            if encode_process.returncode != 0:
                print(f"Retrying encoding process.")
                threading.Thread(target=log_ffmpeg_progress, args=(encode_process,), daemon=True).start()
                encode_process.wait()
                print("ENCODING DONE : ✅")

            # Step 2: Stream the encoded MP3 file to Icecast
            stream_command = [
                'ffmpeg', 
                '-y',              # Overwrite output file without asking
                '-re',             # Read input at native frame rate to avoid overwhelming the system
                '-i', encoded_mp3_path,  # Input encoded MP3 file
                '-f', 'mp3',       # Specify output format as MP3
                '-acodec', 'copy',  # Copy the MP3 codec (no re-encoding)
                '-ab', '192k',     # Set bitrate to 192kbps
                '-ar', '44100',    # Set sample rate to 44100Hz
                '-ac', '2',        # Stereo channels
                '-reconnect', '1', # Reconnect in case of network issues
                '-reconnect_streamed', '1',  # Attempt reconnect for streamed connections
                '-reconnect_delay_max', '10', # Max delay for reconnections
                '-timeout', '3000000',  # Timeout value for connections
                '-flvflags', 'no_duration_filesize',  # Avoid incorrect duration reporting
                '-max_muxing_queue_size', '128',  # Avoid muxing issues
                icecast_url        # Icecast server URL
            ]

            # Start the FFmpeg process
            print("STREAMING STARTED")
            self.ffmpeg_process = subprocess.Popen(
                stream_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1
            )

            # Log streaming progress (same method can be used for streaming)
            threading.Thread(target=log_ffmpeg_progress, args=(self.ffmpeg_process,), daemon=True).start()

            # Wait for the stream to complete
            self.ffmpeg_process.wait()
            print("STREAMING DONE : ✅")

            if self.ffmpeg_process.returncode != 0:
                print(f"FFmpeg streaming error occurred with return code {self.ffmpeg_process.returncode}.")
                # Clean up the temporary MP3 file
                if os.path.exists(encoded_mp3_path):
                    os.remove(encoded_mp3_path)
                return  # Exit the function gracefully without crashing the bot
            
            # Clean up the temporary encoded file
            os.remove(encoded_mp3_path)

        except Exception as e:
            print(f"FFMPEG LOG: {e}")
            # Optionally remove the temporary MP3 file if an error occurs
            if os.path.exists(encoded_mp3_path):
                os.remove(encoded_mp3_path)

    def analyze_volume(self, song_file_path):
        """Analyze the volume of the audio file using FFmpeg."""
        volumedetect_command = [
            'ffmpeg',
            '-i', song_file_path,
            '-af', 'volumedetect',
            '-f', 'null',
            '/dev/null'
        ]

        try:
            process = subprocess.Popen(
                volumedetect_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            _, stderr = process.communicate()

            # Extract mean volume from the output
            mean_volume_match = re.search(r"mean_volume: (-?\d+(\.\d+)?) dB", stderr)
            if mean_volume_match:
                mean_volume = float(mean_volume_match.group(1))
                return mean_volume
            else:
                return None  # Could not analyze volume
        except Exception as e:
            print(f"Error analyzing volume: {e}")
            return None

    async def skip_song(self, user):

        if self.currently_playing:

            # Ensure that skip is not called while a skip action is already in progress
            if self.skip_in_progress:
                await self.highrise.chat("A skip action is already in progress. Please wait.")
                return

            self.skip_in_progress = True  # Flag that a skip action is happening

            try:
                if user.username in self.admins or (self.current_song and self.current_song['owner'] == user.username):
                    async with asyncio.Lock():
                        song_title = self.current_song['title'] if self.current_song else "Unknown"
                        song_owner = self.current_song['owner'] if self.current_song else "Unknown"

                        if user.username == song_owner:
                            await self.highrise.chat(f"@{user.username} skipped:\nSong Name: {song_title}")
                        else:
                            await self.highrise.chat(f"@{user.username} skipped:\nSong Name: {song_title}\nRequested by: @{song_owner}")

                        # Terminate the ffmpeg process if it's running
                        if self.ffmpeg_process is not None:
                            self.ffmpeg_process.terminate()
                            self.ffmpeg_process.wait()
                            self.ffmpeg_process = None
                            print(f"@{user.username} skipped: Song Name: {song_title}")
                        else:
                            print("SKIP SONG : No active ffmpeg process to terminate.")

                        self.currently_playing = False
                        await asyncio.sleep(2)
                        self.skip_event.set()  # Mark that the song was skipped
                else:
                    await self.highrise.chat("Only the requester of the song or an admin can skip it.")
            finally:
                self.skip_in_progress = False  # Reset the skip flag

        else:
            await self.highrise.chat("No song is currently playing to skip.")


    async def stop_existing_stream(self):
        if self.ffmpeg_process:
            print("Attempting to stop active stream...")
            try:
                self.ffmpeg_process.terminate()
                await asyncio.sleep(1)
                if self.ffmpeg_process.poll() is None:
                    print("Stream did not terminate gracefully, forcing kill.")
                    self.ffmpeg_process.kill()
                else:
                    print("Stream terminated gracefully.")
            except Exception as e:
                print(f"Error while stopping the stream: {e}")
            finally:
                print("Clearing FFmpeg process reference.")
                self.ffmpeg_process = None
        else:
            print("No active stream to stop.")

    async def musicbot_dance(self):
        
        while True:

            try:

                if self.song_queue or self.currently_playing:
                    await self.highrise.send_emote('dance-tiktok11', self.highrise.my_id)
                    await asyncio.sleep(9.5)

                else:
                    await self.highrise.send_emote('emote-hello', self.highrise.my_id)
                    await asyncio.sleep(2.7)

            except Exception as e:
                print(f"Error sending emote: {e}")

    def save_queue(self):
        """Save the current song queue to a JSON file."""
        try:
            with open('song_queue.json', 'w') as file:
                json.dump(self.song_queue, file)
        except Exception as e:
            print(f"Error saving queue: {e}")

    def load_queue(self):
        """Load the song queue from a JSON file."""
        try:
            with open('song_queue.json', 'r') as file:
                self.song_queue = json.load(file)
                print("Loaded song queue from file.")
        except FileNotFoundError:
            self.song_queue = []
        except Exception as e:
            print(f"Error loading queue: {e}")

    async def get_actual_pos(self, user_id):

        room_users = await self.highrise.get_room_users()
        
        for user, position in room_users.content:
            if user.id == user_id:
                return position

    def save_loc_data(self):

        loc_data = {
            'bot_position': {'x': self.bot_pos.x, 'y': self.bot_pos.y, 'z': self.bot_pos.z} if self.bot_pos else None,
            'ctoggle': self.ctoggle,
            'nightcore': self.nightcore,
            'daycore': self.daycore,
            'admins': list(self.admins)  # Convert the set to a list for saving
        }

        with open('musicbot_pos.json', 'w') as file:
            json.dump(loc_data, file)

    def load_loc_data(self):

        try:
            with open('musicbot_pos.json', 'r') as file:
                loc_data = json.load(file)
                self.bot_pos = Position(**loc_data.get('bot_position')) if loc_data.get('bot_position') is not None else None
                self.ctoggle = loc_data.get('ctoggle', False)
                self.nightcore = loc_data.get('nightcore', False)
                self.daycore = loc_data.get('daycore', False)
                self.admins = set(loc_data.get('admins', ['NXLN']))  # If 'admins' isn't found, it defaults to an empty list
        except FileNotFoundError:
            pass

    def save_current_song(self):
        with open("current_song.json", "w") as file:
            json.dump(self.current_song, file)

    def load_current_song(self):
        try:
            with open("current_song.json", "r") as file:
                return json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    async def get_user_details(self, user_id: str) -> str:
        # Call the web API to get the user details by user_id
        try:
            response = await self.webapi.get_user(user_id)  # This assumes your API call returns a GetPublicUserResponse object
            if response.user:  # Check if the 'user' attribute exists in the response
                user_data = response.user  # Assuming the response has a 'user' attribute
                return user_data.username  # Return the username (adjust the key as needed)
            else:
                print(f"Error: User data not found in response")
                return None
        except Exception as e:
            print(f"Error fetching user details: {str(e)}")
            return None

    def _debug_node_ipc_env(self, prefix: str) -> None:
        # Temporary debug logging to verify environment cleanup under PM2.
        keys = [
            'NODE_CHANNEL_FD',
            'NODE_UNIQUE_ID',
            'PM2_HOME',
            'PM2_CLUSTER_ADDR',
            'PM2_PID',
            'PM2_PUBLIC_KEY',
            'PM2_RUNTIME_DIR',
            'PM2_GID',
        ]
        present = {k: os.environ.get(k) for k in keys}
        print(f"[yt-dlp-ejs debug] {prefix} NODE/PM2 env: {present}")

    def _cleanup_node_ipc_env(self) -> None:
        # Workaround A: yt-dlp-ejs (deno provider) may rely on NODE_CHANNEL_FD IPC setup.
        # Under PM2 this can point to a non-pipe fd, causing:
        # "Failed to open IPC channel from NODE_CHANNEL_FD".
        # Unset/unexport common NODE IPC env vars right before running yt-dlp.
        for k in ['NODE_CHANNEL_FD', 'NODE_UNIQUE_ID', 'NODE_OPTIONS']:
            if k in os.environ:
                os.environ.pop(k, None)

    async def search_youtube(self, query, user):
        """Search YouTube using yt_dlp, validate, and return the title, duration, and file path (without downloading)."""
        ydl_opts = {

            'format': 'bestaudio/best',
            'default_search': 'ytsearch',
            'quiet': True,
            'noplaylist': True,

            'cookiefile': '/root/cookies.txt',
            'remote_components': 'ejs:github',

            'force_ipv4': True,
            'source_address': '0.0.0.0',

            'js_runtimes': {
                'deno': {
                    'path': '/root/.deno/bin/deno',
                    'args': [
                        '--no-lock',
                    ]
                }
            },

            'extractor_args': {
                'youtube': {
                    'player_client': ['tv', 'web']
                }
            },

            'outtmpl': 'downloads/%(id)s.%(ext)s',

            'ffmpeg_location': '/usr/bin/ffmpeg',
        }  
        try:
            # Workaround A: Clean NODE IPC env right before yt-dlp spawns deno/ejs.
            self._debug_node_ipc_env('before cleanup')
            self._cleanup_node_ipc_env()
            self._debug_node_ipc_env('after cleanup')

            # Perform the search and fetch video info without downloading
            info = await asyncio.to_thread(self._fetch_video_details, query, ydl_opts)


            title = info.get('title')
            duration = info.get('duration')  # Duration in seconds
            file_path = f"downloads/{info['id']}.{info['ext']}" if 'id' in info and 'ext' in info else None

            # Return the fetched details
            return title, duration, file_path, info

        except Exception as e:
            print(f"Error in search_youtube: {e}")
            await self.highrise.chat(f"@{user.username}, there was an error processing your request.")
            return None, None, None, None


    def _fetch_video_details(self, query, ydl_opts):
        """Helper function to fetch video details without downloading."""
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Extract video information only (no download)
                info = ydl.extract_info(query, download=False)
                if 'entries' in info:  # Handle search results
                    info = info['entries'][0]
                return info
        except Exception as e:
            print(f"Error in fetch_video_details: {e}")
            return None


    def _search_info(self, query, ydl_opts):
        """Helper function to search for video info (without downloading) in a separate thread."""
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(query, download=False)  # Just search, don't download
                if 'entries' in info:
                    info = info['entries'][0]
                return info
        except Exception as e:
            print(f"Error in search info: {e}")
            return None
        
    async def download_youtube_audio(self, song_request):
        """Downloads audio from YouTube and returns the local file path."""
        try:
            # Keep the downloader options close to your working version.
            # Goal: avoid postprocessing/extraction issues that can result in an empty output file.

            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': 'downloads/%(id)s.%(ext)s',
                'default_search': 'ytsearch',
                'quiet': True,
                'noplaylist': True,

                'cookiefile': '/root/cookies.txt',
                'remote_components': 'ejs:github',

                'force_ipv4': True,
                'source_address': '0.0.0.0',

                'js_runtimes': {
                    'deno': {
                        'path': '/root/.deno/bin/deno',
                        'args': [
                            '--no-lock',
                        ]
                    }
                },

                'extractor_args': {
                    'youtube': {
                        'player_client': ['tv', 'web']
                    }
                },

                'ffmpeg_options': {
                    'y': True,
                },

                'ffmpeg_location': '/usr/bin/ffmpeg',
                'nocheckcertificate': True,
            }

            # Optional cookies (only if present)
            cookies_path = '/root/cookies.txt'
            if os.path.exists(cookies_path):
                ydl_opts['cookiefile'] = cookies_path

            # If you need deno/ejs runtime in your environment, you can keep it,
            # but avoid extra postprocessors that can break downloads.
            # (Leaving these out by default to match the working minimal approach.)
            # ydl_opts['js_runtimes'] = ...

            with youtube_dl.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(song_request, download=True)
                if not info:
                    return None
                if 'entries' in info:
                    info = info['entries'][0]

                video_id = info.get('id')
                file_extension = info.get('ext')

                if not video_id or not file_extension:
                    return None

                file_path = f"downloads/{video_id}.{file_extension}"

                # Validate: exists + non-empty
                if not os.path.exists(file_path) or os.path.getsize(file_path) <= 0:
                    # Fallback: attempt to get actual downloaded filepath from yt-dlp
                    requested_downloads = info.get('requested_downloads')
                    if requested_downloads and isinstance(requested_downloads, list) and requested_downloads:
                        candidate = requested_downloads[0].get('filepath')
                        if candidate and os.path.exists(candidate) and os.path.getsize(candidate) > 0:
                            file_path = candidate

                if not os.path.exists(file_path) or os.path.getsize(file_path) <= 0:
                    print(f"ERROR: downloaded file missing/empty: {file_path}")
                    return None

                return file_path
        except Exception as e:
            print(f"Error downloading the song: {e}")
            return None


        
    def load_stats(self):
        """Loads stats from a JSON file or initializes an empty dictionary."""
        if os.path.exists("song_stats.json"):
            with open("song_stats.json", "r") as file:
                return json.load(file)
        return {}
    
    def update_song_request_stats(self, title, username):

        # Validate the title
        if not title or not isinstance(title, str):  # Check for None, empty, or non-string titles
            print(f"Invalid song title: {title}. Skipping song stat update.")
            return

        # Check if the song exists in the stats; if not, initialize it
        if title not in self.song_request_counts:
            self.song_request_counts[title] = {
                "count": 0,  # Total request count for the song
                "users": {}  # Per-user request counts
            }

        # Increment the total count for the song
        self.song_request_counts[title]["count"] += 1

        # Increment the user's request count for the song
        if username not in self.song_request_counts[title]["users"]:
            self.song_request_counts[title]["users"][username] = 0
        self.song_request_counts[title]["users"][username] += 1

        # Save the updated stats to the JSON file
        with open("song_stats.json", "w") as file:
            json.dump(self.song_request_counts, file)

    async def view_playlist_songs(self, conversation_id: str, playlist_name: str):
        if playlist_name not in self.playlists:
            await self.highrise.send_message(conversation_id, f"Playlist '{playlist_name}' does not exist.")
            return

        # Access the 'songs' list inside the playlist dictionary
        playlist = self.playlists[playlist_name]
        songs = playlist.get('songs', [])

        if not songs:
            await self.highrise.send_message(conversation_id, f"Playlist '{playlist_name}' is empty.")
            return

        songs_per_batch = 20
        for batch_start in range(0, len(songs), songs_per_batch):
            batch_message = f"Playlist '{playlist_name}' :\n\n"
            batch_end = min(batch_start + songs_per_batch, len(songs))

            for index, song in enumerate(songs[batch_start:batch_end], start=batch_start + 1):
                # Ensure duration is an integer
                duration_seconds = int(song["duration"])  # Convert duration to integer if it's a string
                duration_minutes = duration_seconds // 60
                duration_seconds = duration_seconds % 60
                formatted_duration = f"{duration_minutes}:{duration_seconds:02d}"
                batch_message += f"{index}. {song['title']} ({formatted_duration}) - Added by @{song['added_by']}\n"

            await self.highrise.send_message(conversation_id, batch_message)


    async def add_song_to_playlist(self, conversation_id: str, playlist_name: str, song_query: str, username: str):
        try:
            ydl_opts = {
                'format': 'bestaudio/best',
                'noplaylist': True,
                'extractaudio': True,
                'audioquality': 1,
                'quiet': True,

                'cookiefile': '/root/cookies.txt',
                'remote_components': 'ejs:github',

                'force_ipv4': True,
                'source_address': '0.0.0.0',

                'js_runtimes': {
                    'deno': {
                        'path': '/root/.deno/bin/deno',
                        'args': [
                            '--no-lock',
                        ]
                    }
                },

                'extractor_args': {
                    'youtube': {
                        'player_client': ['tv', 'web']
                    }
                },

                'ffmpeg_location': '/usr/bin/ffmpeg',
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(f"ytsearch:{song_query}", download=False)
                title = info_dict.get('entries', [{}])[0].get('title', 'Unknown Title')
                duration_seconds = info_dict.get('entries', [{}])[0].get('duration', 0)

                # Check if no title or duration is None, and return immediately if so
                if not title or duration_seconds is None:
                    await self.highrise.send_message(conversation_id, f"I couldn't retrieve details for your song request. Please try a different keyword(s) or URL.")
                    return None, None, None

                # Check if the song passed the duration check and return if it doesn't pass
                elif duration_seconds > 12 * 60:  # 12 minutes limit
                    await self.highrise.send_message(conversation_id, f"Your song: '{title}' exceeds the 12-minute duration limit and cannot be added.")
                    return None, None, None

                queue_position = len(self.playlists[playlist_name]["songs"]) + 1

                # Access the 'songs' list inside the playlist dictionary
                self.playlists[playlist_name]["songs"].append({
                    "title": title,
                    "duration": duration_seconds,  # Store duration in seconds as integer
                    "added_by": username,          
                })

                minutes = duration_seconds // 60
                seconds = duration_seconds % 60
                formatted_duration = f"{minutes}:{seconds:02d}"

                await self.highrise.send_message(
    conversation_id,
    (
        f"🎶 Song Added to Queue 🎶\n\n"
        f"🎤 Title: {title}\n"
        f"⏱ Duration: {formatted_duration}\n"
        f"📁 Playlist: {playlist_name}\n"
        f"🎵 Position in Queue: #{queue_position}\n\n"
        f"Get ready for some amazing tunes! 🎧"
    )
                )

                self.save_playlists()

        except Exception as e:
            await self.highrise.send_message(conversation_id, "An error occurred while adding the song.")
            print(f"Error: {e}")

    def save_playlists(self):
        """Save the playlists to a JSON file."""
        try:
            with open(PLAYLIST_FILE, "w") as f:
                json.dump(self.playlists, f, indent=4)
            print("Playlists saved successfully.")
        except Exception as e:
            print(f"Error saving playlists: {e}")

    def load_playlists(self):
        """Load playlists from the JSON file or create it if it doesn't exist."""
        if os.path.exists(PLAYLIST_FILE):
            try:
                with open(PLAYLIST_FILE, "r") as file:
                    print("Loading playlists...")
                    self.playlists = json.load(file)
            except Exception as e:
                print(f"Error loading playlists: {e}")
                self.playlists = {}
        else:
            print(f"{PLAYLIST_FILE} not found. Creating a new one.")
            self.playlists = {}
            self.save_playlists()  # Create the empty file on startup

    async def play_playlist(self, playlist_name, user):

        # Check if playlist exists
        if playlist_name not in self.playlists:
            await self.highrise.chat(f"@{user.username} Playlist '{playlist_name}' does not exist.")
            return

        playlist = self.playlists[playlist_name]

        if not playlist.get("songs"):
            await self.highrise.chat(f"@{user.username} Playlist '{playlist_name}' is empty.")
            return

        # Add songs to the queue in order
        for song in playlist["songs"]:  # Access 'songs' list in the playlist
            title = song.get("title")
            duration = song.get("duration")
            owner = song.get("added_by")

            if not title or not owner:
                print(f"Skipping song due to missing 'title' or 'added_by': {song}")
                continue

            # Add the song to the queue
            self.song_queue.append({
                'title': title,
                'owner': owner,
                'duration': duration
            })

        # Save the updated queue
        self.save_queue()

        # If playback isn't already active, start the playback loop
        if not self.play_task or self.play_task.done():
            print("Playback loop has been created.")
            self.play_task = asyncio.create_task(self.playback_loop())

        # Trigger the event to start processing the queue
        self.play_event.set()

        playlist_length = len(playlist.get("songs", []))
        created_by = playlist.get("created_by") if playlist else "Unknown"

        await self.highrise.chat(
                                f"\n[@{user.username}]\n\n"
                                f"Playlist: {playlist_name}\n"
                                f"Created by: @{created_by}\n"
                                f"Song Count: {playlist_length}\n\n"
                                f"Successfully added to the queue!"
                                )


    def load_logs(self):
            """Load logs and logging state from the .json file, return (logs, logging_enabled)."""
            if os.path.exists(self.log_file):
                with open(self.log_file, 'r') as f:
                    data = json.load(f)
                    # Ensure logs and logging_enabled are always present in the loaded data
                    return data.get('logs', 0), data.get('logging_enabled', True)
            return 0, True  # Default values if the file doesn't exist

    def save_logs(self):
        """Save logs and logging state to the .json file."""
        # Check if the log file path has a directory. If so, ensure that directory exists.
        if os.path.dirname(self.log_file):  # Only try to create a directory if it's specified
            os.makedirs(os.path.dirname(self.log_file), exist_ok=True)

        data = {
            'logs': self.logs,
            'logging_enabled': self.logging_enabled
        }
        with open(self.log_file, 'w') as f:
            json.dump(data, f, indent=4)
