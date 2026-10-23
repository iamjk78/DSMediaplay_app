def action_needs_input(action: str) -> bool:
    """
    Whether an action takes input from the user (the "Input Prompt" window): the names or rows to work on.

    Reading actions (get_*) fetch everything themselves, and so do the "remove_all*" actions and deploying to
    all players. The show_* actions open a window of their own. Everything else (set_*, create_*, the other
    remove_*, deploying selected groups) needs input.
    """
    return not (action.startswith(("get_", "show_")) or "remove_all" in action or action == "set_deploy_all_players")


def entity_actions(actions: dict) -> dict:
    """
    The actions of the application by category: {category: {label shown: key of the action}}. `actions` is the part
    "actions" of the messages in one language (the label of every action); the keys are the same in all of them.
    The documentation is made from this too, so it lists exactly what the window offers.
    """
    return {
        "Playlists": {
            actions["Playlists"]["get_details_csv"]: "get_playlist_details",
            actions["Playlists"]["set_assets_to_playlists"]: "set_assets_to_playlists",
            actions["Playlists"]["remove_assets_from_playlists"]: "remove_assets_from_playlists",
            actions["Playlists"]["create_playlist"]: "create_playlist",
            actions["Playlists"]["get_playlist_unused"]: "get_playlist_unused",
            actions["Playlists"]["remove_unused_playlists"]: "remove_unused_playlists",
            actions["Playlists"]["remove_all_unused_playlists"]: "remove_all_unused_playlists",
            actions["Playlists"]["get_playlist_settings"]: "get_playlist_settings",
            actions["Playlists"]["set_playlist_settings"]: "set_playlist_settings"
        },
        "Groups": {
            # actions["Groups"]["get_groups_playlists_csv"]: "get_groups_with_playlists",
            # actions["Groups"]["set_playlists_to_groups"]: "set_playlists_to_groups",
            actions["Groups"]["get_detailed_groups_playlists_csv"]: "get_detailed_groups_with_playlists",
            actions["Groups"]["set_detailed_playlists_to_groups"]: "set_detailed_playlists_to_groups",
            actions["Groups"]["remove_playlists_from_group"]: "remove_playlists_from_group",
            actions["Groups"]["remove_playlist_list"]: "remove_playlist_list",
            actions["Groups"]["group_rename"]: "set_group_rename",
            actions["Groups"]["get_group_settings"]: "get_group_settings",
            actions["Groups"]["set_group_settings"]: "set_group_settings",
            # actions["Groups"]["set_add_playlist_to_group"]: "set_add_playlist_to_group",
            actions["Groups"]["set_add_detailed_playlist_to_group"]: "set_add_detailed_playlist_to_group",
            actions["Groups"]["remove_expired_playlists"]: "remove_expired_playlists",
            actions["Groups"]["remove_all_expired_playlists"]: "remove_all_expired_playlists",
            actions["Groups"]["create_group"]: "create_group",
            actions["Groups"]["get_group_unused"]: "get_group_unused",
            actions["Groups"]["remove_unused_groups"]: "remove_unused_groups",
            actions["Groups"]["remove_all_unused_groups"]: "remove_all_unused_groups",
            actions["Groups"]["get_identical_groups"]: "get_identical_groups"
        },
        "Players": {
            actions["Players"]["set_groups_to_players"]: "set_groups_to_players",
            actions["Players"]["get_players_groups_csv"]: "get_players_with_groups",
            actions["Players"]["set_notes_to_players"]: "set_notes_to_players",
            actions["Players"]["get_player_locations_csv"]: "get_player_locations",
            actions["Players"]["set_player_config_location"]: "set_player_config_location",
            actions["Players"]["get_player_notes_csv"]: "get_player_notes",
            actions["Players"]["get_player_labels"]: "get_player_categories",
            actions["Players"]["get_label_unused"]: "get_category_unused",
            actions["Players"]["remove_unused_labels"]: "remove_unused_labels",
            actions["Players"]["remove_all_unused_labels"]: "remove_all_unused_labels",
            actions["Players"]["set_player_labels"]: "set_player_labels",
            actions["Players"]["get_player_details"]: "get_player_details",
            actions["Players"]["set_player_rename"]: "set_player_rename",
            actions["Players"]["set_player_snapshot"]: "set_player_snapshot",
            actions["Players"]["show_player_snapshots"]: "show_player_snapshots",
            # actions["Players"]["create_player"]: "create_player",
            actions["Players"]["get_player_versions"]: "get_player_versions",
            actions["Players"]["create_label"]: "create_label",
            actions["Players"]["get_player_overview"]: "get_player_overview",
            actions["Players"]["get_additional_playlists"]: "get_additional_playlists",
            actions["Players"]["remove_additional_playlists"]: "remove_additional_playlists"
        },
        "Locations": {
            actions["Locations"]["get_locations_plan"]: "get_locations_plan",
            actions["Locations"]["set_locations_plan"]: "set_location_plan",
            actions["Locations"]["set_location_rename"]: "set_location_rename",
            actions["Locations"]["create_location"]: "create_location",
            actions["Locations"]["remove_unused_locations"]: "remove_unused_locations",
            actions["Locations"]["remove_all_unused_locations"]: "remove_all_unused_locations",
            actions["Locations"]["get_location_unused"]: "get_location_unused"
        },
        "Assets": {
            actions["Assets"]["get_asset_unused"]: "get_asset_unused",
            actions["Assets"]["remove_unused_assets"]: "remove_unused_assets",
            actions["Assets"]["remove_all_unused_assets"]: "remove_all_unused_assets",
            actions["Assets"]["get_asset_details"]: "get_asset_details",
            actions["Assets"]["get_asset_validity"]: "get_asset_validity",
            actions["Assets"]["set_asset_validity"]: "set_asset_validity"
        },
        "Deploy": {
            actions["Deploy"]["deploy_all_players"]: "set_deploy_all_players",
            actions["Deploy"]["deploy_selected_groups"]: "set_deploy_selected_groups"
        },
    }
