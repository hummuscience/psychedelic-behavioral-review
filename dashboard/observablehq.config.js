// Observable Framework config — psychedelic review dashboard
import {readFileSync, readdirSync} from "node:fs";
import {join} from "node:path";

// Enumerate per-study pages from the consensus directory.
// Use readdirSync (not shell ls + xargs) so filenames with spaces
// like "de la fuente revenga2021.json" are kept intact.
function listStudyStems() {
  try {
    const dir = "../data/results_v2_full_consensus";
    return readdirSync(dir)
      .filter(f => f.endsWith(".json") && !f.startsWith("_"))
      .map(f => f.replace(/\.json$/, ""));
  } catch {
    return [];
  }
}

// URL slug for a study stem: lowercase, alphanumerics only. Keeps page URLs
// space-free (e.g. "lima da cruz2026" -> "limadacruz2026") so hand-typed and
// in-app links agree. The per-study page (study/[stem].md) matches the same
// [^a-z0-9]-stripped key, and slugs are collision-free across the corpus.
const studySlug = (stem) => String(stem).toLowerCase().replace(/[^a-z0-9]/g, "");

const BASE = process.env.OBSERVABLE_BASE || "";

export default {
  title: "Psychedelic Behavioural-Review Dashboard",
  root: "src",
  output: "dist",
  base: BASE || "/",
  cleanUrls: true,
  pages: [
    {name: "Studies over time", path: "/"},
    {name: "Assays",            path: "/assays"},
    {name: "Conditions",        path: "/conditions"},
    {name: "Complexity & duration space", path: "/cube"},
    {name: "Compounds",         path: "/compounds"},
    {name: "Dosages",           path: "/dosages"},
    {name: "Application type",  path: "/applications"},
    {name: "Restrictions",      path: "/restrictions"},
    {name: "Studies table",     path: "/studies"},
    {name: "Pipeline / PRISMA", path: "/pipeline"},
    {name: "Methods",           path: "/methods"},
    {name: "Data downloads",    path: "/data"},
  ],
  search: true,
  theme: ["air", "near-midnight"],
  dynamicPaths: () => listStudyStems().map(stem => `/study/${studySlug(stem)}`),
  header: `<a href="${BASE || '/'}" style="color:inherit;text-decoration:none;">🧠 Psychedelic Behavioural Review</a>`,
  footer: 'Built with <a href="https://observablehq.com/framework/" target="_blank">Observable Framework</a>. Source on <a href="https://github.com/" target="_blank">GitHub</a>.',
  toc: {label: "On this page", show: true},
  head: `<link rel="stylesheet" href="/style.css">`,
};
