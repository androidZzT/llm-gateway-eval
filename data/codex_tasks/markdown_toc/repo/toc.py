def build_toc(markdown: str) -> list[dict]:
    items = []
    for line in markdown.splitlines():
        if line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            title = line[level:].strip()
            items.append({"level": level, "title": title, "slug": title.lower().replace(" ", "-")})
    return items

