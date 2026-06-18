import json
import os
from typing import Any, Dict, List, Optional, Tuple


CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")


class ConfigError(RuntimeError):
    pass


def _deep_get(d: Dict[str, Any], path: List[str], default: Any = None) -> Any:
    cur: Any = d
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def load_config(*, path: str = CONFIG_PATH, require: bool = True) -> Dict[str, Any]:
    """Load config.json.

    If require=True, also validates required top-level fields are present.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except FileNotFoundError as e:
        if require:
            raise ConfigError(f"Missing config file at: {path}") from e
        return {}
    except json.JSONDecodeError as e:
        if require:
            raise ConfigError(f"Invalid JSON in config file: {path}") from e
        return {}

    if require:
        required_paths = [
            ["bot", "token"],
            ["bot", "room_id"],
            ["radio"]
        ]
        for p in required_paths:
            if _deep_get(cfg, p, default=None) is None:
                raise ConfigError(f"Missing required field in config: {'.'.join(p)}")

    # Normalize common structures
    cfg.setdefault("radio", {})
    cfg.setdefault("commands", {})
    cfg.setdefault("messages", {})
    cfg.setdefault("branding", {})

    return cfg


def get_bot_token(cfg: Dict[str, Any]) -> str:
    token = _deep_get(cfg, ["bot", "token"], default=None)
    if not token or not isinstance(token, str):
        raise ConfigError("config.bot.token is missing or invalid")
    return token


def get_room_id(cfg: Dict[str, Any]) -> str:
    room_id = _deep_get(cfg, ["bot", "room_id"], default=None)
    if not room_id or not isinstance(room_id, str):
        raise ConfigError("config.bot.room_id is missing or invalid")
    return room_id


def get_radio_settings(cfg: Dict[str, Any]) -> Dict[str, Any]:
    radio = _deep_get(cfg, ["radio"], default=None)
    if radio is None or not isinstance(radio, dict):
        raise ConfigError("config.radio is missing or invalid")
    return radio


def get_commands(cfg: Dict[str, Any]) -> Dict[str, List[str]]:
    cmds = _deep_get(cfg, ["commands"], default=None)
    if cmds is None or not isinstance(cmds, dict):
        raise ConfigError("config.commands is missing or invalid")

    normalized: Dict[str, List[str]] = {}
    for canonical, aliases in cmds.items():
        if isinstance(aliases, list):
            normalized[canonical] = [str(a) for a in aliases]
        else:
            # allow single string alias
            normalized[canonical] = [str(aliases)]
    return normalized


def get_messages(cfg: Dict[str, Any]) -> Dict[str, str]:
    msgs = _deep_get(cfg, ["messages"], default=None)
    if msgs is None or not isinstance(msgs, dict):
        raise ConfigError("config.messages is missing or invalid")
    return {str(k): str(v) for k, v in msgs.items()}


def get_branding(cfg: Dict[str, Any]) -> Dict[str, Any]:
    branding = _deep_get(cfg, ["branding"], default=None)
    if branding is None or not isinstance(branding, dict):
        raise ConfigError("config.branding is missing or invalid")
    branding.setdefault("enabled", False)
    branding.setdefault("footer", "")
    return branding


def build_alias_map(commands_cfg: Dict[str, List[str]]) -> Dict[str, str]:
    """Returns alias(lowercased) -> canonical_command."""
    alias_map: Dict[str, str] = {}
    for canonical, aliases in commands_cfg.items():
        for a in aliases:
            alias_map[str(a).strip().lower()] = canonical
    return alias_map


def parse_command(config_command_prefix: str, message: str) -> Optional[Tuple[str, str]]:
    """Parse message into (command_alias, rest) based on prefix.

    Supports multi-word commands by checking both one-token and two-token forms.
    If you configure multi-word command aliases, they must match exactly the message tokens.
    """
    if not config_command_prefix:
        return None
    msg = message.strip()
    if not msg.startswith(config_command_prefix):
        return None

    # Remove prefix
    after = msg[len(config_command_prefix) :].strip()
    if not after:
        return None

    # Command can be multi-word; we let the caller match via alias map, but we return the full leading tokens as candidate.
    tokens = after.split()
    if not tokens:
        return None

    # Candidate will be joined by spaces for multi-word matching.
    # Caller can compare against alias_map keys (which may include spaces).
    # We'll return the first token as basic, and the rest as arguments.
    cmd_candidate = tokens[0]
    rest = after[len(cmd_candidate) :].lstrip() if len(after) > len(cmd_candidate) else ""

    return cmd_candidate.lower(), rest

