/**
 * DSH Desktop Pilot — bundled skill provider.
 *
 * The Python runtime stays in this package; this module only registers the
 * `desktop-pilot` skill with the DSH skill registry. No native dependencies,
 * no install-time scripts, no network calls.
 */
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const PROVIDER_NAME = "desktop-pilot";
const SKILL_NAME = "desktop-pilot";
const SKILL_BODY_URL = new URL("../SKILL.md", import.meta.url);
const DP_PATH = fileURLToPath(new URL("../bin/dp.py", import.meta.url));
const RESOURCE_BASE = {
  kind: "directory",
  path: fileURLToPath(new URL("../", import.meta.url)).replace(/\\/g, "/"),
};

function parseSkill(raw, path) {
  const frontmatter = /^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/u.exec(raw);
  if (frontmatter?.[1] === undefined) {
    throw new Error(`desktop-pilot: ${path} has no YAML frontmatter`);
  }
  const description = /^description:\s*(.+)$/mu.exec(frontmatter[1])?.[1]?.trim();
  if (description === undefined || description.length === 0) {
    throw new Error(`desktop-pilot: ${path} has no description`);
  }
  return {
    description,
    content: raw.slice(frontmatter[0].length).trim(),
  };
}

const raw = await readFile(SKILL_BODY_URL, "utf8");
const skill = parseSkill(raw, fileURLToPath(SKILL_BODY_URL));

const CANDIDATE = {
  name: SKILL_NAME,
  description: skill.description,
  whenToUse:
    "Use when a task needs the visible Windows desktop: inspect windows, find a control, click, type Chinese/emoji, press keys, drag, OCR text, or verify that a GUI action actually happened.",
  invocation: {
    modelInvocable: true,
    userInvocable: true,
  },
  provider: PROVIDER_NAME,
  source: "plugin",
  rank: 100,
  resourceBase: RESOURCE_BASE,
  locator: fileURLToPath(SKILL_BODY_URL),
};

const provider = {
  name: PROVIDER_NAME,
  list: () => Promise.resolve([CANDIDATE]),
  async get(_candidate) {
    return {
      name: CANDIDATE.name,
      description: CANDIDATE.description,
      whenToUse: CANDIDATE.whenToUse,
      invocation: CANDIDATE.invocation,
      provider: CANDIDATE.provider,
      source: CANDIDATE.source,
      resourceBase: RESOURCE_BASE,
      content: `${skill.content}

## 本机入口（由插件注入）

插件安装位置已经解析成绝对路径，直接使用，不要猜：

\`\`\`powershell
python "${DP_PATH}" doctor
python "${DP_PATH}" tour
\`\`\`

如果这个路径不存在，说明插件文件被移动了；重新安装插件，或改用目录联接安装。
`,
    };
  },
};

/** Cordis plugin name. */
export const name = "desktop-pilot";

/** Service required by the bundled provider. */
export const inject = ["skills"];

/** Register the bundled `desktop-pilot` provider on `ctx.skills`. */
export function apply(ctx) {
  ctx.skills.registerProvider(() => provider);
}