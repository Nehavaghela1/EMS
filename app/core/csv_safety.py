def csv_safe_cell(value: object) -> str:
    """Sanitize a cell value for CSV export to prevent Formula Injection (CSV Injection).

    Rules:
    - None gives ""
    - An int or float that is NOT a bool gives str(value) unchanged (e.g. -5 stays "-5")
    - Anything else is converted with str(value)
    - If the string starts with '=', '+', '-', '@', '\t' (tab), or '\r' (carriage return),
      it gets a single quote "'" prepended in front.
    - Otherwise, returned unchanged.
    """
    if value is None:
        return ""
    # In Python, bool is a subclass of int, so check bool first
    if not isinstance(value, bool) and isinstance(value, (int, float)):
        return str(value)

    s = str(value)
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{s}"
    return s
