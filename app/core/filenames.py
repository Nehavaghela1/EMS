import re


def sanitize_filename(name: str) -> str:
    """Takes only the last path part (split on / and \\), drops control characters,
    replaces anything outside letters, digits, '.', '_', '-', space with '_',
    strips leading dots and spaces, caps at 100 characters while keeping the extension,
    and returns 'file' if nothing is left.
    """
    if not name or not isinstance(name, str):
        return "file"

    # Take only the last path part (split on / and \)
    name = re.split(r"[/\\]", name)[-1]

    # Drop control characters (ASCII 0-31 and 127)
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)

    # Replace anything outside letters, digits, '.', '_', '-', space with '_'
    name = re.sub(r"[^a-zA-Z0-9._\- ]", "_", name)

    # Strip leading dots and spaces
    name = name.lstrip(". ")

    if not name:
        return "file"

    # Cap at 100 characters while keeping the extension
    if len(name) > 100:
        if "." in name:
            dot_idx = name.rfind(".")
            base = name[:dot_idx]
            ext = name[dot_idx:]  # includes the dot
            # If extension itself is longer than 99, truncate name directly
            if len(ext) >= 100:
                name = name[:100]
            else:
                max_base_len = 100 - len(ext)
                name = base[:max_base_len] + ext
        else:
            name = name[:100]

    return name or "file"
