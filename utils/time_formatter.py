def fmt_time(ms: int) -> str:
    s = max(0, ms // 1000)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02}:{sec:02}"
    return f"{m}:{sec:02}"


def fmt_delay(us: int) -> str:
    """Format microseconds as e.g. '+200 ms' or '-1.5 s'."""
    ms = us // 1000
    if abs(ms) < 1000:
        return f"{ms:+d} ms"
    return f"{ms / 1000:+.1f} s"

