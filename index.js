import fetch from "node-fetch";

const BOT_NAME   = "@agentwaspai";
const COGNEE_API = process.env.COGNEE_SERVICE_URL || "http://localhost:8001";

const MAX_SECTION_CHARS = 2000;
const MAX_COMMENT_CHARS = 60000; // GitHub hard limit is 65536

// GitHub renders raw JSON as an unreadable blob — fence it as code instead
function renderResultText(text) {
  let out = (text || "").trim();

  if (/^[[{]/.test(out)) {
    try {
      out = JSON.stringify(JSON.parse(out), null, 2);
    } catch { /* not valid JSON — fence it anyway */ }
    out = `\`\`\`json\n${out}\n\`\`\``;
  }

  if (out.length > MAX_SECTION_CHARS) {
    out = `${out.slice(0, MAX_SECTION_CHARS)}\n\n_…(truncated)_`;
  }

  return out;
}

function formatRecallReply(question, results) {
  if (!results.length) {
    return "Nothing found in memory. Try `/review` first.";
  }

  const sections = results.map((r, i) => {
    const source = r.dataset_name ? ` — _from \`${r.dataset_name}\`_` : "";
    return `**${i + 1}.**${source}\n\n${renderResultText(r.text)}`;
  });

  const reply = [
    "## AgentWasp AI — Memory Recall",
    "",
    `> **Question:** ${question}`,
    "",
    sections.join("\n\n---\n\n"),
  ].join("\n");

  return reply.length > MAX_COMMENT_CHARS
    ? `${reply.slice(0, MAX_COMMENT_CHARS)}\n\n_…(truncated)_`
    : reply;
}

export default (app) => {
  app.log.info("AgentWasp AI loaded.");

  app.on("issue_comment.created", async (context) => {
    if (context.payload.comment.user?.type === "Bot") return;

    const body     = context.payload.comment.body.trim();
    const number   = context.payload.issue.number;
    const repo     = context.payload.repository.full_name;

    if (!body.toLowerCase().includes(BOT_NAME.toLowerCase())) return;

    // ── /review ───────────────────────────────────────────────
    if (body.toLowerCase().includes("/review")) {
      if (!context.payload.issue.pull_request) {
        await context.octokit.rest.issues.createComment(
          context.issue({ body: "This command only works on pull requests." })
        );
        return;
      }

      try {
        const [
          { data: diff },
          { data: files },
          { data: comments },
          { data: reviewComments },
          { data: reviews },
          { data: commits },
        ] = await Promise.all([
          context.octokit.rest.pulls.get({
            ...context.repo(),
            pull_number: number,
            mediaType: { format: "diff" },
          }),
          context.octokit.rest.pulls.listFiles({
            ...context.repo(),
            pull_number: number,
          }),
          context.octokit.rest.issues.listComments({
            ...context.repo(),
            issue_number: number,
          }),
          context.octokit.rest.pulls.listReviewComments({
            ...context.repo(),
            pull_number: number,
          }),
          context.octokit.rest.pulls.listReviews({
            ...context.repo(),
            pull_number: number,
          }),
          context.octokit.rest.pulls.listCommits({
            ...context.repo(),
            pull_number: number,
          }),
        ]);

        app.log.info({ diff, files, comments, reviewComments, reviews, commits });

        // post raw summary to PR
        const summary = `
**Raw PR Data**
- Files changed: ${files.length}
- Commits: ${commits.length}
- Comments: ${comments.length}
- Review comments: ${reviewComments.length}
- Reviews: ${reviews.length}

**Files**
${files.map(f => `- \`${f.filename}\` [${f.status}] +${f.additions} -${f.deletions}`).join("\n")}

**Commits**
${commits.map(c => `- \`${c.sha.slice(0, 7)}\` ${c.commit.message} (${c.commit.author.name})`).join("\n")}

**Diff preview**
\`\`\`diff
${diff.slice(0, 1000)}
\`\`\`
        `.trim();

        await context.octokit.rest.issues.createComment(
          context.issue({ body: summary })
        );

        // ingest to Cognee
        const ingestRes = await fetch(`${COGNEE_API}/ingest`, {
          method:  "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            repo,
            pr_number:       number,
            diff,
            files,
            commits,
            comments,
            review_comments: reviewComments,
            reviews,
          }),
        });

        if (!ingestRes.ok) throw new Error(`Ingest failed: ${ingestRes.status}`);

        const ingestResult = await ingestRes.json();
        app.log.info(`Ingest response: ${JSON.stringify(ingestResult)}`);

        await context.octokit.rest.issues.createComment(
          context.issue({
            body: `PR #${number} data stored in memory and ready for review.`,
          })
        );

      } catch (err) {
        app.log.error(`Review failed: ${err.message}`);
        await context.octokit.rest.issues.createComment(
          context.issue({ body: `Error: ${err.message}` })
        );
      }
      return;
    }

    // ── /ask ──────────────────────────────────────────────────
    if (body.toLowerCase().includes("/ask")) {
      const question = body
        .replace(new RegExp(BOT_NAME, "gi"), "")
        .replace(/\/ask/i, "")
        .trim();

      if (!question || question.length < 3) {
        await context.octokit.rest.issues.createComment(
          context.issue({ body: "Please provide a question after `/ask`." })
        );
        return;
      }

      try {
        const recallRes = await fetch(`${COGNEE_API}/recall`, {
          method:  "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            query:     question,
            repo,
            pr_number: number,
          }),
        });

        if (!recallRes.ok) throw new Error(`Recall failed: ${recallRes.status}`);

        const { results } = await recallRes.json();

        await context.octokit.rest.issues.createComment(
          context.issue({ body: formatRecallReply(question, results) })
        );

      } catch (err) {
        app.log.error(`Ask failed: ${err.message}`);
        await context.octokit.rest.issues.createComment(
          context.issue({ body: `Error: ${err.message}` })
        );
      }
      return;
    }
  });
};