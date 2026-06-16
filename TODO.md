# TODO - Music Bot Refactor to Central Config

- [x] Create `config.json` scaffold with bot token, radio/icecast, commands, messages, branding.
- [x] Add `bot.command_prefix` to `config.json`.
- [x] Remove guild/voice channel placeholders from `config.json` (use `room.id` instead).
- [ ] Wire `musicbot.py` to load `config.json` dynamically and support `reload`.
- [ ] Update `main.py` to read bot token + room id from `config.json`.
- [ ] Remove hardcoded radio/icecast values from `musicbot.py` and load from `config.json`.
- [ ] Replace hardcoded command names/prefix strings with config-driven command parsing (supports aliases + multi-word).
- [ ] Centralize static messages into config and ensure placeholders still work.
- [ ] Implement global branding footer appending to supported responses.
- [ ] Run a quick syntax check / basic import test after refactor.

