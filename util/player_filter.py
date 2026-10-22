import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, FrozenSet, Iterable, List, Optional, Tuple

MILLISECONDS_FROM = 10 ** 11  # as seconds this is the year 5138, as milliseconds 1973: nothing real is in between


@dataclass(frozen=True)
class PlayerRow:
    name: str
    online: bool
    group: str  # "" = the player belongs to no group
    location: str
    labels: Tuple[str, ...]
    synced: Optional[datetime]  # when the content was last uploaded to the player; None = never
    reported: Optional[datetime]  # when the player last reported to the server; None = never
    note: str
    temperature: Optional[float]  # of the processor in degrees Celsius; None = the player does not say
    version: str  # of the player software
    player_id: str = ""  # the server's id of the player; what a snapshot is asked for by


@dataclass(frozen=True)
class AgeFilter:
    """How long ago a moment has to be: `op` "<" = less than `seconds` ago, ">" = more than `seconds` ago."""
    op: str
    seconds: int


MINUTE, HOUR, DAY = 60, 3600, 86400
# The choices of the "synced" and "reported" filters: the key of the text in messages.json ("pb_age_<key>") and the
# criterion. A moment that never happened is older than any time ago, so it matches every ">" and no "<".
AGE_OPTIONS: Tuple[Tuple[str, AgeFilter], ...] = (
    ("lt_1m", AgeFilter("<", MINUTE)),
    ("gt_1m", AgeFilter(">", MINUTE)),
    ("gt_5m", AgeFilter(">", 5 * MINUTE)),
    ("gt_60m", AgeFilter(">", 60 * MINUTE)),
    ("gt_3h", AgeFilter(">", 3 * HOUR)),
    ("gt_6h", AgeFilter(">", 6 * HOUR)),
    ("gt_12h", AgeFilter(">", 12 * HOUR)),
    ("gt_1d", AgeFilter(">", DAY)),
    ("gt_1w", AgeFilter(">", 7 * DAY)),
    ("gt_1mo", AgeFilter(">", 30 * DAY)),
)


@dataclass(frozen=True)
class TemperatureFilter:
    """`op` ">": hotter than `value` degrees; "none": the player does not report a temperature."""
    op: str
    value: float = 0


# The choices of the temperature filter: the key of the text in messages.json ("pb_temp_<key>") and the criterion
TEMPERATURE_OPTIONS: Tuple[Tuple[str, TemperatureFilter], ...] = (
    ("gt_50", TemperatureFilter(">", 50)),
    ("gt_60", TemperatureFilter(">", 60)),
    ("gt_70", TemperatureFilter(">", 70)),
    ("gt_80", TemperatureFilter(">", 80)),
    ("none", TemperatureFilter("none")),
)


@dataclass(frozen=True)
class PlayerFilter:
    """
    A criterion left at its default does not filter. The criteria are combined with AND. For group, location and
    category there is a text (a part of the value) and a set of chosen values: a player has to match the text and
    be one of the chosen values ("" stands for no group); with several chosen values any of them is enough.
    """
    name: str = ""
    online: Optional[bool] = None
    group_text: str = ""
    groups: FrozenSet[str] = field(default_factory=frozenset)
    location_text: str = ""
    locations: FrozenSet[str] = field(default_factory=frozenset)
    label_text: str = ""
    labels: FrozenSet[str] = field(default_factory=frozenset)
    synced: Optional[AgeFilter] = None
    reported: Optional[AgeFilter] = None
    note: str = ""
    temperature: Optional[TemperatureFilter] = None
    version_text: str = ""
    versions: FrozenSet[str] = field(default_factory=frozenset)


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


def parse_temperature(value: Any) -> Optional[float]:
    """The server sends the temperature as text ("47", "47.2", "temp=47.2'C"); no number in it means no temperature."""
    if isinstance(value, bool) or value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    found = re.search(r"-?\d+(?:[.,]\d+)?", str(value))
    return float(found.group().replace(",", ".")) if found else None


def version_key(version: str) -> Tuple:
    """5.10.2 comes after 5.9.7: the numbers of a version are compared as numbers."""
    return tuple((0, int(part)) if part.isdigit() else (1, part.casefold()) for part in re.split(r"[.\-_/ ]+", version)
                 if part)


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
        reported=parse_timestamp(player.get("lastReported")),
        note=" ".join(str(player.get("notes") or "").split()),  # one line: a note can contain line breaks
        temperature=parse_temperature(player.get("piTemperature")),
        version=str(player.get("version") or "").strip(),
        player_id=str(player.get("_id") or ""),
    )


def plain_text(text: str) -> str:
    """Lower case without diacritics, so "praha" finds "Lobby Praha" and "Přerov" alike."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(character for character in decomposed if not unicodedata.combining(character))


def _contains(text: str, value: str) -> bool:
    return not text.strip() or plain_text(text.strip()) in plain_text(value)


def _age_matches(moment: Optional[datetime], criterion: Optional[AgeFilter], now: datetime) -> bool:
    if criterion is None:
        return True
    if moment is None:
        return criterion.op == ">"
    age = (now - moment).total_seconds()
    return age < criterion.seconds if criterion.op == "<" else age > criterion.seconds


def _temperature_matches(temperature: Optional[float], criterion: Optional[TemperatureFilter]) -> bool:
    if criterion is None:
        return True
    if criterion.op == "none":
        return temperature is None
    return temperature is not None and temperature > criterion.value


def matches(row: PlayerRow, criteria: PlayerFilter, now: datetime) -> bool:
    return (_contains(criteria.name, row.name)
            and (criteria.online is None or row.online == criteria.online)
            and _contains(criteria.group_text, row.group)
            and (not criteria.groups or row.group in criteria.groups)
            and _contains(criteria.location_text, row.location)
            and (not criteria.locations or row.location in criteria.locations)
            and (not criteria.label_text.strip() or any(_contains(criteria.label_text, label) for label in row.labels))
            and (not criteria.labels or bool(criteria.labels.intersection(row.labels)))
            and _age_matches(row.synced, criteria.synced, now)
            and _age_matches(row.reported, criteria.reported, now)
            and _contains(criteria.note, row.note)
            and _temperature_matches(row.temperature, criteria.temperature)
            and _contains(criteria.version_text, row.version)
            and (not criteria.versions or row.version in criteria.versions))


def apply_filter(rows: Iterable[PlayerRow], criteria: PlayerFilter, now: Optional[datetime] = None) -> List[PlayerRow]:
    now = now or datetime.now()
    return [row for row in rows if matches(row, criteria, now)]


SORT_KEYS: Dict[str, Callable[[PlayerRow], Any]] = {
    "name": lambda row: plain_text(row.name),
    "status": lambda row: (not row.online, plain_text(row.name)),  # online first
    "group": lambda row: (plain_text(row.group), plain_text(row.name)),
    "location": lambda row: (plain_text(row.location), plain_text(row.name)),
    "label": lambda row: (plain_text(", ".join(row.labels)), plain_text(row.name)),
    "synced": lambda row: (row.synced is None, row.synced or datetime.min, plain_text(row.name)),
    "reported": lambda row: (row.reported is None, row.reported or datetime.min, plain_text(row.name)),
    "note": lambda row: (plain_text(row.note), plain_text(row.name)),
    "temperature": lambda row: (row.temperature is None, row.temperature or 0.0, plain_text(row.name)),
    "version": lambda row: (not row.version, version_key(row.version), plain_text(row.name)),
}


# The columns whose sort key starts with "there is nothing here": those players always come last, whichever way
# the column is sorted (reversing the whole key would bring them to the top of a descending sort)
MISSING_LAST = ("synced", "reported", "temperature", "version")


def sort_rows(rows: Iterable[PlayerRow], column: str, descending: bool = False) -> List[PlayerRow]:
    key = SORT_KEYS[column]
    if column not in MISSING_LAST:
        return sorted(rows, key=key, reverse=descending)
    ordered = sorted(rows, key=lambda row: key(row)[1:], reverse=descending)
    return sorted(ordered, key=lambda row: key(row)[0])  # stable: what has a value stays in its order, first
