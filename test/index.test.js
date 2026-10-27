import nock from "nock";
import myProbotApp from "../index.js";
import { Probot, ProbotOctokit } from "probot";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import payload from "./fixtures/pull_request.opened.json" with { type: "json" };
import { describe, beforeEach, afterEach, test } from "node:test";
import assert from "node:assert";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const privateKey = fs.readFileSync(
  path.join(__dirname, "fixtures/mock-cert.pem"),
  "utf-8",
);

describe("My Probot app", () => {
  let probot;

  beforeEach(() => {
    nock.disableNetConnect();
    probot = new Probot({
      appId: 123,
      privateKey,
      Octokit: ProbotOctokit.defaults((instanceOptions) => ({
        ...instanceOptions,
        retry:    { enabled: false },
        throttle: { enabled: false },
      })),
    });
    probot.load(myProbotApp);
  });

  afterEach(() => {
    nock.cleanAll();
    nock.enableNetConnect();
  });


  // ── Test 1 — PR opened, context fetched ──────────────────────

  test("fetches PR context when pull request is opened", async () => {
    const mock = nock("https://api.github.com")
      .post("/app/installations/2/access_tokens")
      .reply(200, { token: "test", permissions: { pull_requests: "read" } })

      // diff
      .get("/repos/hiimbex/testing-things/pulls/1")
      .matchHeader("accept", "application/vnd.github.v3.diff")
      .reply(200, "diff --git a/file.js b/file.js\n+new line")

      // files
      .get("/repos/hiimbex/testing-things/pulls/1/files")
      .reply(200, [{ filename: "file.js", status: "modified", additions: 1, deletions: 0, patch: "+new line" }])

      // comments
      .get("/repos/hiimbex/testing-things/issues/1/comments")
      .reply(200, [])

      // review comments
      .get("/repos/hiimbex/testing-things/pulls/1/comments")
      .reply(200, [])

      // reviews
      .get("/repos/hiimbex/testing-things/pulls/1/reviews")
      .reply(200, [])

      // commits
      .get("/repos/hiimbex/testing-things/pulls/1/commits")
      .reply(200, [{ sha: "abc1234", commit: { message: "fix: test", author: { name: "hiimbex" } } }]);

    await probot.receive({ name: "pull_request", payload });

    assert.deepStrictEqual(mock.pendingMocks(), []);
  });


  // ── Test 2 — mention in comment ──────────────────────────────

  test("replies when the bot is mentioned in a comment", async () => {
    const issueCommentPayload = {
      action: "created",
      comment: {
        body: "hello @agentwaspai can you help?",
        user: { type: "User" },
      },
      issue: { number: 1 },
      repository: { name: "testing-things", owner: { login: "hiimbex" } },
      installation: { id: 2 },
    };

    const mock = nock("https://api.github.com")
      .post("/app/installations/2/access_tokens")
      .reply(200, { token: "test", permissions: { issues: "write" } })

      .post("/repos/hiimbex/testing-things/issues/1/comments", (body) => {
        // just confirm a reply was posted — don't assert exact INTRO_MESSAGE text
        assert.ok(body.body.length > 0);
        return true;
      })
      .reply(200, { id: 456 });

    await probot.receive({ name: "issue_comment", payload: issueCommentPayload });

    assert.deepStrictEqual(mock.pendingMocks(), []);
  });
});