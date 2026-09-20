import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

MILLISECONDS_FROM = 10 ** 11  # as seconds this is the year 5138, as milliseconds 1973: nothing real is in between


@dataclass(frozen=True)
class PlayerRow:
    name: str
    online: bool
    group: str  # "" = the player belongs to no group
    location: str
    labels: Tuple[str, ...]
    synced: Optional[datetime]  # when the content was last uploaded to the player; None = never


@dataclass(frozen=True)
class PlayerFilter:
    """
    A criterion left at None (or "" for the name) does not filter. `group == ""` selects the players without a
    group. The criteria are combined with AND.
    """
    name: str = ""
    group: Optional[str] = None
    label: Optional[str] = None
    location: Optional[str] = None
    online: Optional[bool] = None


def parse_timestamp(value: Any) -> Optional[datetime]:
    """The server sends epoch milliseconds (or an ISO string); 0, None and anything unreadable mean "never"."""
    if isinstance(value, bool) or value in (None, "", 0):
        return None
    try:
        if isinstance(value, str):
            try:
                value = float(value)
            except ValueError:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
        seconds = value / 1000 if value >= MILLISECONDS_FROM else value
        return datetime.fromtimestamp(seconds)
    except (ValueError, OverflowError, OSError, TypeError):
        return None


def player_row(player: Dict[str, Any]) -> PlayerRow:
    """The row of one player object as the server returns it."""
    group = player.get("group") or {}
    return PlayerRow(
        name=player.get("name", ""),
        online=bool(player.get("licensed", True) and player.get("isConnected", False)),
        group=group.get("name", "") if isinstance(group, dict) else "",
        location=player.get("configLocation") or player.get("location") or "",
        labels=tuple(player.get("labels") or ()),
        synced=parse_timestamp(player.get("lastUpload")),
    )


def _plain(text: str) -> str:
    """Lower case without diacritics, so "praha" finds "Lobby Praha" and "Přerov" alike."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(character for character in decomposed if not unicodedata.combining(character))


def matches(row: PlayerRow, criteria: PlayerFilter) -> bool:
    return ((not criteria.name.strip() or _plain(criteria.name.strip()) in _plain(row.name))
            and (criteria.group is None or row.group == criteria.group)
            and (criteria.label is None or criteria.label in row.labels)
            and (criteria.location is None or row.location == criteria.location)
            and (criteria.online is None or row.online == criteria.online))


def apply_filter(rows: Iterable[PlayerRow], criteria: PlayerFilter) -> List[PlayerRow]:
    return [row for row in rows if matches(row, criteria)]


SORT_KEYS: Dict[str, Callable[[PlayerRow], Any]] = {
    "name": lambda row: _plain(row.name),
    "status": lambda row: (not row.online, _plain(row.name)),  # online first
    "group": lambda row: (_plain(row.group), _plain(row.name)),
    "location": lambda row: (_plain(row.location), _plain(row.name)),
    "synced": lambda row: (row.synced is None, row.synced or datetime.min, _plain(row.name)),
}


def sort_rows(rows: Iterable[PlayerRow], column: str, descending: bool = False) -> List[PlayerRow]:
    return sorted(rows, key=SORT_KEYS[column], reverse=descending)
