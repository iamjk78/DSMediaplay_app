import unicodedata


# What is handed to an action that takes no input, so that "there is something" holds for every action
NO_INPUT_PLACEHOLDER = "Non-empty"


def action_needs_input(action: str) -> bool:
    """
    Whether an action takes input from the user (the "Input Prompt" window): the names or rows to work on.

    Reading actions (get_*) fetch everything themselves, and so do the "remove_all*" actions and deploying to
    all players. The show_* actions open a window of their own. Everything else (set_*, create_*, the other
    remove_*, deploying selected groups) needs input.
    """
    return not (action.startswith(("get_", "show_")) or "remove_all" in action
                or action == "set_deploy_all_players")


# Actions that take input but also run without it (the input narrows them down)
OPTIONAL_INPUT_ACTIONS = ("set_player_assets_check",)


def action_input_optional(action: str) -> bool:
    """Whether the action may start with an empty input (then it works on everything it can)."""
    return action in OPTIONAL_INPUT_ACTIONS


KIND_ORDER = ("read", "change", "remove")  # the blocks of a list of actions, green, blue, red


def action_kind(action: str) -> str:
    """
    What an action does, for tinting it in the list of actions: "read" (the CSV exports), "remove" (removing and
    deleting) or "change" (everything else: setting, adding, renaming, creating, the snapshots, deploying).
    """
    if action.startswith("get_"):
        return "read"
    if action.startswith("remove_"):
        return "remove"
    return "change"


def _list_position(item: tuple) -> tuple:
    """Sort key of a (label, action key) pair: the block (by colour), then the label by the alphabet, accents aside."""
    label, action = item
    plain = "".join(c for c in unicodedata.normalize("NFD", label) if not unicodedata.combining(c))
    return KIND_ORDER.index(action_kind(action)), plain.casefold(), label


def entity_actions(actions: dict) -> dict:
    """
    The actions of the application by category: {category: {label shown: key of the action}}. `actions` is the part
    "actions" of the messages in one language (the label of every action); the keys are the same in all of them.
    Within a category the actions are in the order the window and the documentation show them: the reading ones
    (green), the changing ones (blue), the removing ones (red), each block by the alphabet of its labels, so the
    order they are written in below does not matter.
    """
    categories = {
        "Playlists": {
            actions["Playlists"]["get_details_csv"]: "get_playlist_details",
            actions["Playlists"]["get_playlist_settings"]: "get_playlist_settings",
            actions["Playlists"]["get_playlist_unused"]: "get_playlist_unused",
            actions["Playlists"]["set_assets_to_playlists"]: "set_assets_to_playlists",
            actions["Playlists"]["set_playlist_settings"]: "set_playlist_settings",
            actions["Playlists"]["remove_assets_from_playlists"]: "remove_assets_from_playlists",
            actions["Playlists"]["remove_unused_playlists"]: "remove_unused_playlists",
            actions["Playlists"]["remove_all_unused_playlists"]: "remove_all_unused_playlists",
            actions["Playlists"]["create_playlist"]: "create_playlist"
        },
        "Groups": {
            # actions["Groups"]["get_groups_playlists_csv"]: "get_groups_with_playlists",
            # actions["Groups"]["set_playlists_to_groups"]: "set_playlists_to_groups",
            # actions["Groups"]["set_add_playlist_to_group"]: "set_add_playlist_to_group",
            actions["Groups"]["get_detailed_groups_playlists_csv"]: "get_detailed_groups_with_playlists",
            actions["Groups"]["get_group_settings"]: "get_group_settings",
            actions["Groups"]["get_group_unused"]: "get_group_unused",
            actions["Groups"]["get_identical_groups"]: "get_identical_groups",
            actions["Groups"]["set_detailed_playlists_to_groups"]: "set_detailed_playlists_to_groups",
            actions["Groups"]["set_group_settings"]: "set_group_settings",
            actions["Groups"]["group_rename"]: "set_group_rename",
            actions["Groups"]["set_add_detailed_playlist_to_group"]: "set_add_detailed_playlist_to_group",
            actions["Groups"]["remove_playlists_from_group"]: "remove_playlists_from_group",
            actions["Groups"]["remove_playlist_list"]: "remove_playlist_list",
            actions["Groups"]["remove_expired_playlists"]: "remove_expired_playlists",
            actions["Groups"]["remove_all_expired_playlists"]: "remove_all_expired_playlists",
            actions["Groups"]["remove_unused_groups"]: "remove_unused_groups",
            actions["Groups"]["remove_all_unused_groups"]: "remove_all_unused_groups",
            actions["Groups"]["create_group"]: "create_group"
        },
        "Players": {
            # actions["Players"]["create_player"]: "create_player",
            actions["Players"]["get_players_groups_csv"]: "get_players_with_groups",
            actions["Players"]["get_player_locations_csv"]: "get_player_locations",
            actions["Players"]["get_player_notes_csv"]: "get_player_notes",
            actions["Players"]["get_player_labels"]: "get_player_categories",
            actions["Players"]["get_label_unused"]: "get_category_unused",
            actions["Players"]["get_player_details"]: "get_player_details",
            actions["Players"]["get_player_versions"]: "get_player_versions",
            actions["Players"]["get_player_overview"]: "get_player_overview",
            actions["Players"]["get_additional_playlists"]: "get_additional_playlists",
            actions["Players"]["set_groups_to_players"]: "set_groups_to_players",
            actions["Players"]["set_notes_to_players"]: "set_notes_to_players",
            actions["Players"]["set_player_config_location"]: "set_player_config_location",
            actions["Players"]["set_player_labels"]: "set_player_labels",
            actions["Players"]["set_player_rename"]: "set_player_rename",
            actions["Players"]["remove_additional_playlists"]: "remove_additional_playlists",
            actions["Players"]["remove_unused_labels"]: "remove_unused_labels",
            actions["Players"]["remove_all_unused_labels"]: "remove_all_unused_labels",
            actions["Players"]["create_label"]: "create_label",
            actions["Players"]["set_player_snapshot"]: "set_player_snapshot",
            actions["Players"]["show_player_snapshots"]: "show_player_snapshots",
            actions["Players"]["set_player_assets_check"]: "set_player_assets_check"
        },
        "Locations": {
            actions["Locations"]["get_locations_plan"]: "get_locations_plan",
            actions["Locations"]["get_location_unused"]: "get_location_unused",
            actions["Locations"]["set_locations_plan"]: "set_location_plan",
            actions["Locations"]["set_location_rename"]: "set_location_rename",
            actions["Locations"]["remove_unused_locations"]: "remove_unused_locations",
            actions["Locations"]["remove_all_unused_locations"]: "remove_all_unused_locations",
            actions["Locations"]["create_location"]: "create_location"
        },
        "Assets": {
            actions["Assets"]["get_asset_details"]: "get_asset_details",
            actions["Assets"]["get_asset_validity"]: "get_asset_validity",
            actions["Assets"]["get_asset_unused"]: "get_asset_unused",
            actions["Assets"]["set_asset_validity"]: "set_asset_validity",
            actions["Assets"]["remove_unused_assets"]: "remove_unused_assets",
            actions["Assets"]["remove_all_unused_assets"]: "remove_all_unused_assets"
        },
        "Deploy": {
            actions["Deploy"]["deploy_all_players"]: "set_deploy_all_players",
            actions["Deploy"]["deploy_selected_groups"]: "set_deploy_selected_groups"
        },
    }
    return {category: dict(sorted(items.items(), key=_list_position)) for category, items in categories.items()}
