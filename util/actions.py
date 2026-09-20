def action_needs_input(action: str) -> bool:
    """
    Whether an action takes input from the user (the "Input Prompt" window): the names or rows to work on.

    Reading actions (get_*) fetch everything themselves, and so do the "remove_all*" actions and deploying to
    all players. The show_* actions open a window of their own. Everything else (set_*, create_*, the other
    remove_*, deploying selected groups) needs input.
    """
    return not (action.startswith(("get_", "show_")) or "remove_all" in action or action == "set_deploy_all_players")
