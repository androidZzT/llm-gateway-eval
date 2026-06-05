import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const html = readFileSync("index.html", "utf8");
const css = readFileSync("styles.css", "utf8");
const js = readFileSync("app.js", "utf8");
const combined = `${html}\n${css}\n${js}`;

assert.match(html, /id=["']app["']/i);
assert.match(html, /styles\.css/i);
assert.match(html, /app\.js/i);
assert.doesNotMatch(combined, /https?:\/\//i);
assert.doesNotMatch(css, /font-size\s*:[^;]*vw/i);
assert.doesNotMatch(css, /letter-spacing\s*:\s*-/i);
assert.match(css, /@media/i, "responsive CSS required");
assert.match(css, /grid|flex/i, "layout styling required");
assert.match(css, /article-card|post-card|post-list/i, "article card styling required");

const sandbox = { module: { exports: {} }, exports: {}, window: {}, console };
vm.runInNewContext(js, sandbox, { filename: "app.js" });
const api = Object.keys(sandbox.module.exports).length ? sandbox.module.exports : sandbox.window.AgenticNotes;

for (const fn of [
  "normalizePosts",
  "getBlogStats",
  "filterPosts",
  "selectFeaturedPosts",
  "formatReadTime",
  "renderBlog"
]) {
  assert.equal(typeof api?.[fn], "function", `${fn} must be exported`);
}

assert.equal(api.posts.length, 5);
for (const title of [
  "Harness 到底指什么",
  "复杂任务的 Spec 怎么写",
  "Harness 怎么扩展：skill、配置目录与 hook",
  "Claude Code 把编排写进代码：Dynamic Workflows 详解",
  "给 Claude Code 装个 profiler：每个工具调用慢在哪，瀑布流时间线里一眼看见"
]) {
  assert.ok(api.posts.some((post) => post.title === title), `missing post: ${title}`);
}
assert.ok(api.posts.every((post) => post.sourcePath.startsWith("~/Claude/wechat/")));

const normalized = api.normalizePosts(api.posts);
assert.equal(normalized[0].id, "cctrace-launch", "posts should be newest first");
assert.equal(normalized.at(-1).id, "harness-definition", "oldest post should be last");
assert.equal(normalized[0].year, "2026");
assert.ok(normalized[0].searchText.toLowerCase().includes("profiler"));
assert.equal(api.formatReadTime(1320), "6 分钟");

const stats = api.getBlogStats(api.posts);
assert.equal(stats.totalPosts, 5);
assert.ok(stats.totalWords > 25000);
assert.ok(stats.totalReadMinutes >= 100);
assert.equal(stats.seriesCounts["SDD / Harness Engineering"], 3);
assert.equal(stats.tagCounts.harness, 2);
assert.equal(stats.tagCounts.workflow, 2);

assert.deepEqual(
  api.filterPosts(api.posts, { query: "profiler", tag: "all", series: "all" }).map((post) => post.id),
  ["cctrace-launch"]
);
assert.deepEqual(
  api.filterPosts(api.posts, { query: "", tag: "workflow", series: "all" }).map((post) => post.id),
  ["dynamic-workflows", "spec-for-complex-tasks"]
);
assert.deepEqual(
  api.filterPosts(api.posts, { query: "skill", tag: "all", series: "SDD / Harness Engineering" }).map((post) => post.id),
  ["harness-extension", "spec-for-complex-tasks"]
);

const featured = api.selectFeaturedPosts(api.posts, 3).map((post) => post.id);
assert.deepEqual(featured, ["cctrace-launch", "dynamic-workflows", "harness-extension"]);

const rendered = api.renderBlog({
  query: "",
  tag: "all",
  series: "all",
  selectedPostId: "cctrace-launch"
});
for (const phrase of [
  "Agentic Notes",
  "个人博客",
  "Harness 到底指什么",
  "复杂任务的 Spec 怎么写",
  "Dynamic Workflows",
  "cctrace",
  "搜索",
  "标签",
  "系列",
  "时间线",
  "订阅",
  "精选",
  "阅读",
  "~/Claude/wechat/cctrace-launch/article.md"
]) {
  assert.ok(rendered.toLowerCase().includes(phrase.toLowerCase()), `rendered UI missing ${phrase}`);
}
assert.match(rendered, /id=["']post-search["']/i);
assert.match(rendered, /id=["']tag-filter["']/i);
assert.match(rendered, /id=["']series-filter["']/i);
assert.match(rendered, /data-post-id=["']cctrace-launch["']/i);
assert.ok(rendered.length > 7000, "rendered blog should be substantial");
