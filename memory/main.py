import asyncio
import os
import cognee

from dotenv import load_dotenv
from pydantic import BaseModel
from cognee.infrastructure.llm.LLMGateway import LLMGateway
from config.rules import SYSTEM_RULES, REVIEW_RULES, ASK_RULES

load_dotenv()


# ── Response models ───────────────────────────────────────────────

class ReviewResponse(BaseModel):
    review: str

class AskResponse(BaseModel):
    answer: str


# ── /review agent ─────────────────────────────────────────────────
#
# memory_query_fixed      — always searches for review rules + past PR patterns
# memory_system_prompt    — tells the model how to use the retrieved memory
# save_traces=True        — saves every review as memory so future reviews
#                           learn from what the bot said before
# agent_session_name      — stable name so Cognee tracks this agent's history
#                           across calls in Cognee Cloud Connections view

@cognee.agent_memory(
    agent_session_name="agentwaspai-review",
    dataset_name="agent_memory_dataset",
    memory_query_fixed="code review rules standards past PR issues bugs",
    memory_system_prompt=REVIEW_RULES,
    #with_memory=True,
    #save_traces=True,
    memory_top_k=5,
)
async def review_agent(pr_context: str) -> ReviewResponse:
    """
    Decorator prepends relevant memory (rules + past reviews) to the LLM call.
    LLMGateway picks it up automatically — no extra code needed here.
    pr_context is the full structured PR document built by Probot.
    """
    return await LLMGateway.acreate_structured_output(
        text_input=pr_context,
        system_prompt=REVIEW_RULES,
        response_model=ReviewResponse,
    )


# ── /ask agent ────────────────────────────────────────────────────
#
# memory_query_from_method="question"
#   — uses the actual question as the Cognee search query
#   — so memory retrieval changes per question, not fixed
# with_session_memory=True
#   — also pulls in recent Q&A traces from this session
#   — so the bot remembers what it said earlier in the same conversation

@cognee.agent_memory(
    agent_session_name="agentwaspai-ask",
    dataset_name="agent_memory_dataset",
    memory_query_from_method="question",
    memory_system_prompt=ASK_RULES,
    #with_memory=True,
    #with_session_memory=True,   # remember what was asked earlier in this PR session
    #save_traces=True,
    memory_top_k=5,
)
async def ask_agent(question: str, pr_context: str) -> AskResponse:
    """
    memory_query_from_method="question" means Cognee searches memory
    using the question itself as the query — so if the user asks about
    async handling, Cognee returns everything it knows about async issues
    in this codebase.
    pr_context is passed separately as the current PR data.
    """
    return await LLMGateway.acreate_structured_output(
        text_input=f"Question: {question}\n\nPR Context:\n{pr_context}",
        system_prompt=ASK_RULES,
        response_model=AskResponse,
    )


# ── Main setup — run once at startup ─────────────────────────────

async def setup():
    """
    Connect to Cognee Cloud and load rules into memory.
    Call this once when the FastAPI service starts.
    """
    await cognee.serve(
        url=os.getenv("COGNEE_API_URL"),
        api_key=os.getenv("COGNEE_API_KEY"),
    )
    print("Connected to Cognee Cloud")

    # load rules into memory — these become the base knowledge
    # the decorator retrieves from on every call
    await cognee.remember(
        data=SYSTEM_RULES,
        dataset_name="agent_memory_dataset",
    )
    print("Rules loaded into memory")


# ── Test ──────────────────────────────────────────────────────────

async def main():
    await setup()

    # test review agent
    test_pr = """
    PR #5 — fix: add error handling to getUserById
    Author: hiimbex
    Files: src/db/users.js

    Diff:
    - async function getUserById(id) {
    -   return await db.users.findUnique({ where: { id } })
    + async function getUserById(id) {
    +   try {
    +     return await db.users.findUnique({ where: { id } })
    +   } catch (err) {
    +     throw new DatabaseError(err)
    +   }
    """

    print("\n--- Review Agent ---")
    review = await review_agent(pr_context=test_pr)
    print(review.review)

    print("\n--- Ask Agent ---")
    answer = await ask_agent(
        question="why does getUserById need error handling?",
        pr_context=test_pr,
    )
    print(answer.answer)

    await cognee.disconnect()


if __name__ == "__main__":
    asyncio.run(main())