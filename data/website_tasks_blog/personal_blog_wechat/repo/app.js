const posts = [
  {
    id: "harness-definition",
    title: "Harness 到底指什么",
    subtitle: "谈 Coding Agent 的平台层与业务工程的边界",
    date: "2026-05-21",
    series: "SDD / Harness Engineering",
    sourcePath: "~/Claude/wechat/01-what-is-harness/article.md",
    tags: ["harness", "agent", "platform", "sdd"],
    words: 5200,
    featured: true,
    excerpt: "Harness 是 Coding Agent 平台层：上下文管理、记忆、subagent 编排、skill 机制、工具调用、hook 与运行闭环。业务工程建在它之上，不应去改它。",
    takeaway: "把 SDD 与 Harness Engineering 分层，才能讲清业务 spec 与 agent 运行时的边界。"
  },
  {
    id: "spec-for-complex-tasks",
    title: "复杂任务的 Spec 怎么写",
    subtitle: "多 Agent、编排者入口、rules/docs/skills 组织与 skill 分层",
    date: "2026-05-25",
    series: "SDD / Harness Engineering",
    sourcePath: "~/Claude/wechat/02-skill-layering/article.md",
    tags: ["spec", "multi-agent", "skills", "workflow"],
    words: 6100,
    featured: false,
    excerpt: "复杂任务不该让一个 Agent 从头干到尾。编排者只做阶段判断、门禁和收口，具体工作交给职责清晰的专职子 Agent。",
    takeaway: "入口文件应该薄，规则、知识、步骤分层存放，复杂协作才不会变成提示词泥潭。"
  },
  {
    id: "harness-extension",
    title: "Harness 怎么扩展：skill、配置目录与 hook",
    subtitle: "CC 与 Codex 的两套扩展机制",
    date: "2026-05-29",
    series: "SDD / Harness Engineering",
    sourcePath: "~/Claude/wechat/03-harness-extension/article.md",
    tags: ["harness", "skill", "hook", "codex", "claude-code"],
    words: 5600,
    featured: true,
    excerpt: "Skill、配置目录和 hook 是两套 coding agent 生态都在打磨的扩展入口。真正的差异不在有没有，而在面对同一问题时工程解法不同。",
    takeaway: "Skill 的 description 要写触发条件，不是能力广告；配置层要讲清个人、项目和企业约束的覆盖关系。"
  },
  {
    id: "dynamic-workflows",
    title: "Claude Code 把编排写进代码：Dynamic Workflows 详解",
    subtitle: "当任务大到一次对话装不下，让 Claude 把编排过程写成脚本",
    date: "2026-05-30",
    series: "Agent Runtime",
    sourcePath: "~/Claude/wechat/dynamic-workflows/article.md",
    tags: ["workflow", "claude-code", "orchestration", "runtime"],
    words: 4800,
    featured: true,
    excerpt: "Dynamic Workflows 的核心转变，是把计划搬进代码。循环、分支和中间结果由本地 JavaScript 运行时持有，LLM 只在 agent() 调用处临时接入。",
    takeaway: "当中间结果太多时，编排从对话变成程序，主 Agent 只需要醒来读取最终结论。"
  },
  {
    id: "cctrace-launch",
    title: "给 Claude Code 装个 profiler：每个工具调用慢在哪，瀑布流时间线里一眼看见",
    subtitle: "把会话铺成瀑布流时间线，每个工具调用一眼看清",
    date: "2026-06-02",
    series: "Tooling",
    sourcePath: "~/Claude/wechat/cctrace-launch/article.md",
    tags: ["cctrace", "profiler", "timeline", "observability", "codex"],
    words: 3900,
    featured: true,
    excerpt: "cctrace 把 Claude Code 或 Codex 会话包装成可回放的瀑布流时间线，关联 process、transcript 与 ccglass 三路事件。",
    takeaway: "终端输出只能告诉你发生过什么，trace 时间线能告诉你时间到底花在哪里。"
  }
];

function normalizePosts(inputPosts = posts) {
  // TODO: return posts sorted by newest first with readTime, year, month, tagText, and searchText.
  return inputPosts;
}

function getBlogStats(inputPosts = posts) {
  // TODO: return totals, reading minutes, tag counts, and series counts.
  return {};
}

function filterPosts(inputPosts = posts, filters = {}) {
  // TODO: filter by query, tag, and series after normalizing posts.
  return inputPosts;
}

function selectFeaturedPosts(inputPosts = posts, limit = 3) {
  // TODO: prefer featured posts, then newest posts, limited by the requested count.
  return inputPosts.slice(0, limit);
}

function formatReadTime(words) {
  // TODO: format Chinese reading time at roughly 220 words per minute.
  return String(words);
}

function renderBlog(state = {}) {
  // TODO: render the complete blog HTML.
  return "";
}

function mount() {
  const root = typeof document !== "undefined" ? document.getElementById("app") : null;
  if (!root) return;
  let state = { query: "", tag: "all", series: "all", selectedPostId: "cctrace-launch" };
  const render = () => {
    root.innerHTML = renderBlog(state);
    root.querySelector("#post-search")?.addEventListener("input", (event) => {
      state = { ...state, query: event.target.value };
      render();
    });
    root.querySelector("#tag-filter")?.addEventListener("change", (event) => {
      state = { ...state, tag: event.target.value };
      render();
    });
    root.querySelector("#series-filter")?.addEventListener("change", (event) => {
      state = { ...state, series: event.target.value };
      render();
    });
    root.querySelectorAll("[data-post-id]").forEach((item) => {
      item.addEventListener("click", () => {
        state = { ...state, selectedPostId: item.getAttribute("data-post-id") };
        render();
      });
    });
  };
  render();
}

const api = {
  posts,
  normalizePosts,
  getBlogStats,
  filterPosts,
  selectFeaturedPosts,
  formatReadTime,
  renderBlog
};

if (typeof window !== "undefined") {
  window.AgenticNotes = api;
  mount();
}

if (typeof module !== "undefined") {
  module.exports = api;
}
