def wheel_units(delta: int, aqua: bool) -> int:
    """
    How many lines a turn of the mouse wheel scrolls. macOS reports lines already; Windows reports multiples of 120,
    and a precision touchpad there reports much smaller steps, which must still scroll one line up as well as down
    (`-delta // 120` rounded -40 to -1 but 40 to 0, so the touchpad scrolled in one direction only).
    """
    if aqua:
        return -delta
    if delta == 0:
        return 0
    lines = max(1, abs(delta) // 120)
    return -lines if delta > 0 else lines
