"""
The state an action is about to change, saved before it does: for every action that overwrites or deletes something,
the CSV exports (processor/csv_generator.py) that hold what the action overwrites or loses. The actions that only add
(creating, adding playlists to a group) or only rename (the log names the old and the new name) are not in it.
Keyed by the type of the processor, as the log window knows the action.
"""
from typing import Dict, Tuple

_GROUPS_WITH_PLAYLISTS = ("detailed_groups_with_playlists",)
_UNUSED_GROUPS = ("group_settings", "detailed_groups_with_playlists")
_UNUSED_PLAYLISTS = ("playlist_settings", "playlist_details")

BACKUPS: Dict[str, Tuple[str, ...]] = {
    "player_group": ("players_with_groups",),
    "player_note": ("player_notes",),
    "player_config_location": ("player_locations",),
    "player_labels": ("player_categories",),
    "detailed_playlist": _GROUPS_WITH_PLAYLISTS,
    "remove_playlists": _GROUPS_WITH_PLAYLISTS,
    "remove_playlist_list": _GROUPS_WITH_PLAYLISTS,
    "remove_expired_playlists": _GROUPS_WITH_PLAYLISTS,
    "remove_all_expired_playlists": _GROUPS_WITH_PLAYLISTS,
    "group_settings": ("group_settings",),
    "remove_unused_groups": _UNUSED_GROUPS,
    "remove_all_unused_groups": _UNUSED_GROUPS,
    "asset_to_playlist": ("playlist_details",),
    "remove_assets": ("playlist_details",),
    "playlist_settings": ("playlist_settings",),
    "remove_unused_playlists": _UNUSED_PLAYLISTS,
    "remove_all_unused_playlists": _UNUSED_PLAYLISTS,
    "location_plan": ("locations_plan",),
    "remove_unused_locations": ("locations_plan",),
    "remove_all_unused_locations": ("locations_plan",),
    "asset_validity": ("asset_validity",),
    "remove_unused_assets": ("asset_details",),
    "remove_all_unused_assets": ("asset_details",),
    "remove_unused_labels": ("category_unused",),
    "remove_all_unused_labels": ("category_unused",),
    "remove_additional_playlists": ("additional_playlists",),
}


def csv_tasks_for(processor_type: str) -> Tuple[str, ...]:
    """The CSV exports that save what the action changes; none for an action that needs no backup."""
    return BACKUPS.get(processor_type, ())
