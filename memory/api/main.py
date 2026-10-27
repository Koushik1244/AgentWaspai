import os
import cognee
import logging

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("AgentWasp AI starting up")
    yield
    logger.info("AgentWasp AI shutting down")


app = FastAPI(title="AgentWasp AI", lifespan=lifespan)


# ── Models ────────────────────────────────────────────────────────

class PRDataRequest(BaseModel):
    repo: str
    pr_number: int
    diff: str
    files: list
    commits: list
    comments: list
    review_comments: list
    reviews: list


class RecallRequest(BaseModel):
    query: str
    repo: str = ""
    pr_number: int = 0


# ── Helper — connect to Cognee Cloud ─────────────────────────────

async def connect():
    await cognee.serve(
        url=os.getenv("COGNEE_API_URL"),
        api_key=os.getenv("COGNEE_API_KEY"),
    )
    logger.info("Connected to Cognee Cloud")


def serialize_pr_data(body: PRDataRequest) -> str:
    """
    Build a structured markdown document from the raw GitHub PR payload.

    Cognee chunks and embeds this document, and /recall returns those chunks
    verbatim. Storing clean markdown here means recalled chunks come back as
    readable markdown instead of a minified JSON blob that GitHub comments
    cannot render.
    """
    lines = [
        f"# PR #{body.pr_number} — {body.repo}",
        "",
        "## Files Changed",
    ]

    for f in body.files:
        path = f.get("filename") or f.get("path") or "unknown"
        lines.append(
            f"- `{path}` [{f.get('status', '?')}] "
            f"+{f.get('additions', 0)} -{f.get('deletions', 0)}"
        )
    if not body.files:
        lines.append("None")

    lines += ["", "## Commits"]
    for c in body.commits:
        sha = str(c.get("sha", ""))[:7]
        commit = c.get("commit", {})
        message = (commit.get("message") or c.get("message") or "").splitlines()[0]
        author = (commit.get("author") or {}).get("name") or c.get("author") or ""
        lines.append(f"- `{sha}` {message} ({author})".strip())
    if not body.commits:
        lines.append("None")

    lines += ["", "## Diff", "```diff", body.diff[:4000], "```"]

    lines += ["", "## Inline Review Comments"]
    review_comments = [c for c in body.review_comments if (c.get("user") or {}).get("type") != "Bot"]
    for c in review_comments:
        author = (c.get("user") or {}).get("login", "unknown")
        lines.append(f"- [{c.get('path', '?')} line {c.get('line', '?')}] {author}: {c.get('body', '')}")
    if not review_comments:
        lines.append("None")

    lines += ["", "## Discussion"]
    comments = [c for c in body.comments if (c.get("user") or {}).get("type") != "Bot"]
    for c in comments:
        author = (c.get("user") or {}).get("login", "unknown")
        lines.append(f"- {author}: {c.get('body', '')}")
    if not comments:
        lines.append("None")

    lines += ["", "## Formal Reviews"]
    reviews = [r for r in body.reviews if (r.get("user") or {}).get("type") != "Bot" and r.get("body")]
    for r in reviews:
        author = (r.get("user") or {}).get("login", "unknown")
        lines.append(f"- {author} [{r.get('state', '?')}]: {r.get('body', '')}")
    if not reviews:
        lines.append("None")

    return "\n".join(lines)


# ── Recall result helpers ────────────────────────────────────────
#
# cognee.recall returns dict-like results:
#   {'kind': ..., 'text': '...markdown...', 'raw': {'value': '...'}, ...}
# getattr(r, "text", str(r)) misses on dicts and falls back to str(r),
# which produces a Python-repr blob that GitHub comments can't render.

def result_field(r, key, default=""):
    if isinstance(r, dict):
        return r.get(key, default) or default
    return getattr(r, key, default) or default


def result_text(r) -> str:
    text = result_field(r, "text")
    if text:
        return text

    raw = result_field(r, "raw")
    if isinstance(raw, dict) and raw.get("value"):
        return raw["value"]

    return str(r)


# ── Routes ────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "ok", "service": "AgentWasp AI"}


@app.post("/ingest")
async def ingest(body: PRDataRequest):
    try:
        await connect()

        raw_document = serialize_pr_data(body)

        logger.info(f"Ingesting PR #{body.pr_number} from {body.repo}")
        logger.info(f"Document preview:\n{raw_document[:300]}")

        await cognee.remember(
            data=raw_document,
            dataset_name=f"repo-{body.repo.replace('/', '-')}",
        )

        logger.info(f"PR #{body.pr_number} stored in Cognee Cloud")

        return {
            "status":    "ok",
            "pr_number": body.pr_number,
            "repo":      body.repo,
        }

    except Exception as e:
        logger.error(f"Ingest failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/recall")
async def recall(body: RecallRequest):
    try:
        # connect every request
        await connect()

        # search the dataset /ingest wrote to — repo-inline-arc-AgentwaspAi
        # is the fallback for queries that don't name a repo
        dataset = (
            f"repo-{body.repo.replace('/', '-')}"
            if body.repo
            else "repo-inline-arc-AgentwaspAi"
        )

        results = await cognee.recall(
            query_text=body.query,
            datasets=[dataset]
            )

        context = [
            {
                "text":         result_text(r),
                "dataset_name": result_field(r, "dataset_name"),
                "source":       result_field(r, "source"),
            }
            for r in results
        ]

        logger.info(f"Recall returned {len(context)} results for: {body.query}")

        return {
            "status":  "ok",
            "query":   body.query,
            "results": context,
        }

    except Exception as e:
        logger.error(f"Recall failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))