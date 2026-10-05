import re

_SOURCE_HEADING = re.compile(
    r" {0,3}##[ \t]+(?:Sources|Source GitHub issues|Source issues)"
    r"(?:[ \t]+#+)?[ \t]*"
)
_SOURCE_LINK = re.compile(
    r"[-*+] \[(?:Issue #\d+|Merged PR #\d+|Open docs PR #\d+|"
    r"Existing docs:|#\d+)[^\n]*\]\([^\n]+\)"
)
_FENCE = re.compile(r" {0,3}(`{3,}|~{3,})(.*)")
_NO_SOURCES = "- No linked repository sources were available."


def without_generated_sources(markdown: str) -> str:
    """Remove a trailing evidence appendix without truncating document content."""
    lines = markdown.splitlines(keepends=True)
    source_heading = None
    fence = None
    for index, raw_line in enumerate(lines):
        line = raw_line.rstrip("\r\n")
        if fence is not None:
            if re.fullmatch(rf" {{0,3}}{fence[0]}{{{len(fence)},}}[ \t]*", line):
                fence = None
            continue
        opening = _FENCE.fullmatch(line)
        if opening and not (
            opening[1].startswith("`") and "`" in opening[2]
        ):
            fence = opening[1]
            continue
        if _SOURCE_HEADING.fullmatch(line):
            source_heading = index

    if source_heading is not None:
        appendix = [
            line.rstrip("\r\n")
            for line in lines[source_heading + 1 :]
            if line.strip()
        ]
        if appendix and all(
            not line.startswith(("    ", "\t"))
            and (_SOURCE_LINK.fullmatch(line.strip()) or line.strip() == _NO_SOURCES)
            for line in appendix
        ):
            return "".join(lines[:source_heading]).rstrip()
    return markdown.strip()
