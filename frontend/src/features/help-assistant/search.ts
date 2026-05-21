import { HELP_ARTICLES } from "./helpCorpus";
import type { HelpArticle, HelpSearchResult } from "./types";

const COMMON_WORDS = new Set([
  "a",
  "an",
  "and",
  "are",
  "can",
  "do",
  "for",
  "how",
  "i",
  "in",
  "is",
  "it",
  "me",
  "my",
  "of",
  "on",
  "or",
  "the",
  "this",
  "to",
  "use",
  "what",
  "with"
]);

export function normalizeHelpText(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9_:/.-]+/g, " ").replace(/\s+/g, " ").trim();
}

export function tokenizeHelpQuery(query: string): string[] {
  const normalized = normalizeHelpText(query);
  if (!normalized) {
    return [];
  }
  return Array.from(
    new Set(
      normalized
        .split(" ")
        .map((term) => term.trim())
        .filter((term) => term.length > 1 && !COMMON_WORDS.has(term))
    )
  );
}

function articleSearchText(article: HelpArticle): string {
  return normalizeHelpText(
    [
      article.title,
      article.audience,
      article.summary,
      ...article.body,
      ...article.steps,
      ...article.keywords,
      ...article.sources.map((source) => `${source.label} ${source.path}`)
    ].join(" ")
  );
}

function scoreArticle(article: HelpArticle, terms: string[]): HelpSearchResult {
  const title = normalizeHelpText(article.title);
  const keywords = article.keywords.map(normalizeHelpText);
  const summary = normalizeHelpText(article.summary);
  const text = articleSearchText(article);
  const matchedTerms: string[] = [];
  let score = 0;

  for (const term of terms) {
    if (title.includes(term)) {
      score += 10;
      matchedTerms.push(term);
      continue;
    }
    if (keywords.some((keyword) => keyword.includes(term) || term.includes(keyword))) {
      score += 8;
      matchedTerms.push(term);
      continue;
    }
    if (summary.includes(term)) {
      score += 5;
      matchedTerms.push(term);
      continue;
    }
    if (text.includes(term)) {
      score += 2;
      matchedTerms.push(term);
    }
  }

  return { article, score, matchedTerms };
}

export function searchHelpArticles(
  query: string,
  articles: HelpArticle[] = HELP_ARTICLES,
  limit = 4
): HelpSearchResult[] {
  const terms = tokenizeHelpQuery(query);
  if (terms.length === 0) {
    return articles.slice(0, limit).map((article, index) => ({
      article,
      score: articles.length - index,
      matchedTerms: []
    }));
  }

  return articles
    .map((article) => scoreArticle(article, terms))
    .filter((result) => result.score > 0)
    .sort((left, right) => right.score - left.score || left.article.title.localeCompare(right.article.title))
    .slice(0, limit);
}

export function getBestHelpArticle(query: string): HelpArticle {
  return searchHelpArticles(query, HELP_ARTICLES, 1)[0]?.article ?? HELP_ARTICLES[0];
}
