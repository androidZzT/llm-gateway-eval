Complete the static personal blog website for `Agentic Notes`.

This is a benchmark task: the exact same prompt will be used for an official Codex baseline and a gateway/proxy Codex target. Keep the implementation concise, but make the result feel like a real personal blog, not a generic template. Prefer filling TODOs and improving the existing files instead of rewriting everything.

The blog data in `app.js` was extracted from several markdown drafts under `~/Claude/wechat`. Do not read the filesystem at runtime. Use the provided data as the source of truth and preserve the source-path provenance in the UI.

Goal:
- Build a polished personal blog for writing about AI agent engineering, harness design, workflows, skills, and profiling.
- Make the first screen feel editorial and technical, with the latest or featured article visible immediately.
- The site should be useful as a portfolio/blog homepage: readers can scan posts, filter by topic, inspect a selected article, and see a timeline.

Edit:
- `index.html`
- `styles.css`
- `app.js`

Required:
- No build step, package manager, external CDN, external image, or network call.
- Keep the app static and openable through `index.html`.
- Implement the exported JS functions in `app.js`:
  - `normalizePosts(posts)`
  - `getBlogStats(posts)`
  - `filterPosts(posts, filters)`
  - `selectFeaturedPosts(posts, limit)`
  - `formatReadTime(words)`
  - `renderBlog(state)`
- Keep exposing them via `module.exports` and `window.AgenticNotes`.
- Use all provided posts in the rendered UI.
- The rendered UI must include: personal brand, editorial hero, featured post, search, tag filter, series filter, article cards, selected article detail, source path/provenance, tag cloud, reading timeline, newsletter/subscribe action, and at least one visible metric about posts or reading time.
- Style is your choice, but it should be visually polished, responsive, and content-first.
- Avoid oversized marketing-only hero treatment; keep actual article content visible in the first viewport.

Run `bash ./verify.sh` before finishing.
