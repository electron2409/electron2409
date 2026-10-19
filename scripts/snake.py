#!/usr/bin/env python3
"""Generate an animated "reverse snake" contribution graph.

The whole grid is green. The snake only eats the squares where nothing was
pushed, so the days you did push stay on the board when the snake is done.

Usage:
    python scripts/snake.py <github-username> <output-dir>
    python scripts/snake.py demo dist --demo      # synthetic data, for testing

Set GITHUB_TOKEN to read contributions through the GraphQL API. Without a
token the script falls back to the public contributions page.
"""
import datetime as dt
import json
import os
import random
import re
import sys
import urllib.request

CELL = 11          # square size
PITCH = 14         # square size + gap
MARGIN = 18
SNAKE_LEN = 6
STEP = 0.05        # seconds per square
PAUSE_STEPS = 40   # time the finished board stays on screen before looping

THEMES = {
    "github-contribution-grid-snake.svg": {          # light page
        "empty": "#9be9a8",
        "levels": ["#40c463", "#30a14e", "#216e39", "#0b4a24"],
        "head": "#ff4fa3",
        "body": "#ff8fc7",
    },
    "github-contribution-grid-snake-dark.svg": {     # dark page
        "empty": "#0e4429",
        "levels": ["#1f8a3a", "#26a641", "#39d353", "#7ee787"],
        "head": "#ff4fa3",
        "body": "#ff8fc7",
    },
}


# ---------------------------------------------------------------- data ----
def count_to_level(count):
    if count <= 0:
        return 0
    if count <= 2:
        return 1
    if count <= 5:
        return 2
    if count <= 9:
        return 3
    return 4


def fetch_graphql(login, token):
    query = """query($login:String!){user(login:$login){contributionsCollection{
      contributionCalendar{weeks{contributionDays{date contributionCount weekday}}}}}}"""
    body = json.dumps({"query": query, "variables": {"login": login}}).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql", data=body,
        headers={"Authorization": f"Bearer {token}", "User-Agent": "snake-gen"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    weeks = data["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
    grid = []
    for w in weeks:
        col = [None] * 7
        for d in w["contributionDays"]:
            col[d["weekday"]] = count_to_level(d["contributionCount"])
        grid.append(col)
    return grid


def fetch_html(login):
    req = urllib.request.Request(
        f"https://github.com/users/{login}/contributions",
        headers={"User-Agent": "snake-gen"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read().decode("utf-8", "replace")
    cells = {}
    for tag in re.findall(r"<td[^>]*>", html):
        date = re.search(r'data-date="(\d{4}-\d{2}-\d{2})"', tag)
        level = re.search(r'data-level="(\d)"', tag)
        if date and level:
            cells[dt.date.fromisoformat(date.group(1))] = int(level.group(1))
    if not cells:
        raise RuntimeError("no contribution cells found on the page")
    first = min(cells)
    start = first - dt.timedelta(days=(first.weekday() + 1) % 7)   # back to Sunday
    n_weeks = (max(cells) - start).days // 7 + 1
    grid = [[None] * 7 for _ in range(n_weeks)]
    for day, level in cells.items():
        grid[(day - start).days // 7][(day.weekday() + 1) % 7] = level
    return grid


def demo_grid():
    rnd = random.Random(7)
    grid = []
    for w in range(53):
        col = []
        for d in range(7):
            if w == 52 and d > 3:
                col.append(None)
            else:
                col.append(rnd.choice([0, 0, 0, 0, 1, 2, 3, 4]) if w > 38 else 0)
        grid.append(col)
    return grid


def load_grid(login, demo):
    if demo:
        return demo_grid()
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        try:
            return fetch_graphql(login, token)
        except Exception as exc:
            print(f"GraphQL failed ({exc}); trying the public page", file=sys.stderr)
    return fetch_html(login)


# ----------------------------------------------------------------- svg ----
def build_path(grid):
    """Zig-zag through every existing square, column by column."""
    path = []
    for c, col in enumerate(grid):
        days = range(7) if c % 2 == 0 else range(6, -1, -1)
        for d in days:
            if col[d] is not None:
                path.append((c, d))
    return path


def render(grid, theme):
    path = build_path(grid)
    n_cells = len(path)
    steps = n_cells + SNAKE_LEN + PAUSE_STEPS          # frames in one loop
    last = steps - 1
    dur = last * STEP
    width = MARGIN * 2 + len(grid) * PITCH - (PITCH - CELL)
    height = MARGIN * 2 + 7 * PITCH - (PITCH - CELL)

    def pos(c, d):
        return MARGIN + c * PITCH, MARGIN + d * PITCH

    order = {cd: i for i, cd in enumerate(path)}
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Contribution graph where a snake eats the empty days">'
    ]

    # squares
    for c, col in enumerate(grid):
        for d, level in enumerate(col):
            if level is None:
                continue
            x, y = pos(c, d)
            if level == 0:
                t = max(order[(c, d)], 0.5) / last
                out.append(
                    f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="2" '
                    f'fill="{theme["empty"]}">'
                    f'<animate attributeName="opacity" calcMode="discrete" values="1;0" '
                    f'keyTimes="0;{t:.5f}" dur="{dur:.2f}s" repeatCount="indefinite"/></rect>'
                )
            else:
                color = theme["levels"][min(level, 4) - 1]
                out.append(
                    f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="2" '
                    f'fill="{color}"/>'
                )

    # snake segments (head = k 0)
    key_times = ";".join(f"{s / last:.5f}" for s in range(steps))
    for k in range(SNAKE_LEN - 1, -1, -1):
        coords, opac = [], []
        base = 1.0 - k * 0.13
        for s in range(steps):
            i = s - k
            idx = min(max(i, 0), n_cells - 1)
            x, y = pos(*path[idx])
            coords.append(f"{x} {y}")
            opac.append(f"{base:.2f}" if 0 <= i < n_cells else "0")
        fill = theme["head"] if k == 0 else theme["body"]
        out.append(
            f'<rect width="{CELL}" height="{CELL}" rx="3" fill="{fill}" opacity="0">'
            f'<animateTransform attributeName="transform" type="translate" '
            f'values="{";".join(coords)}" keyTimes="{key_times}" '
            f'dur="{dur:.2f}s" repeatCount="indefinite"/>'
            f'<animate attributeName="opacity" calcMode="discrete" '
            f'values="{";".join(opac)}" keyTimes="{key_times}" '
            f'dur="{dur:.2f}s" repeatCount="indefinite"/></rect>'
        )

    out.append("</svg>")
    return "\n".join(out)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    demo = "--demo" in sys.argv
    login = args[0] if args else "electron2409"
    out_dir = args[1] if len(args) > 1 else "dist"
    grid = load_grid(login, demo)
    os.makedirs(out_dir, exist_ok=True)
    pushed = sum(1 for col in grid for v in col if v)
    total = sum(1 for col in grid for v in col if v is not None)
    for name, theme in THEMES.items():
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as fh:
            fh.write(render(grid, theme))
    print(f"Wrote {len(THEMES)} files to {out_dir}: {total} days, {pushed} with pushes")


if __name__ == "__main__":
    main()
