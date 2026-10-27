from pathlib import Path

RULES_DIR = Path(__file__).parent.parent / "rules"

def load_rules(filename: str) -> str:
    return (RULES_DIR / filename).read_text(encoding="utf-8")

ASK_RULES = load_rules("ask.txt");
REVIEW_RULES = load_rules("review.txt");
SYSTEM_RULES = load_rules("rules.txt");
CLAUDE_RULES = load_rules("claude.md");