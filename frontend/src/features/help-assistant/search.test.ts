import { describe, expect, it } from "vitest";

import { HELP_ARTICLES } from "./helpCorpus";
import { getBestHelpArticle, searchHelpArticles, tokenizeHelpQuery } from "./search";

describe("help assistant search", () => {
  it("normalizes beginner setup questions into useful terms", () => {
    expect(tokenizeHelpQuery("How do I connect my OpenRouter to this AGENT33 repo?")).toEqual([
      "connect",
      "openrouter",
      "agent33",
      "repo"
    ]);
  });

  it("deduplicates repeated query terms before scoring", () => {
    expect(tokenizeHelpQuery("docker docker docker health")).toEqual(["docker", "health"]);
  });

  it("returns the OpenRouter setup recipe for model-provider questions", () => {
    const result = getBestHelpArticle("how do i connect openrouter model provider");

    expect(result.id).toBe("connect-openrouter");
    expect(result.body.join(" ")).toContain("OPENROUTER_API_KEY");
    expect(result.body.join(" ")).toContain("OPENROUTER_BASE_URL=https://openrouter.ai/api/v1");
    expect(result.body.join(" ")).toContain("DEFAULT_MODEL=openrouter/auto");
  });

  it("keeps answers cited and local-only for the MVP corpus", () => {
    const result = getBestHelpArticle("docker health frontend");

    expect(result.id).toBe("start-docker");
    expect(result.sources.length).toBeGreaterThan(0);
    expect(result.body.join(" ")).not.toContain("sk-");
  });

  it("falls back to popular articles when the query is empty", () => {
    const results = searchHelpArticles("");

    expect(results).toHaveLength(4);
    expect(results[0]?.article.id).toBe(HELP_ARTICLES[0]?.id);
  });
});
