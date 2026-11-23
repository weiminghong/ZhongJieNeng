import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { resolve, dirname } from "node:path";
const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const source = readFileSync(resolve(root, "DESIGN.md"), "utf8");
const match = source.match(/```json design-tokens\s*([\s\S]*?)```/);
if (!match) throw new Error("DESIGN.md 缺少 design-tokens 合同");
const themes = JSON.parse(match[1]);
const names = Object.keys(themes["standard-light"]);
const header = "/* Generated from DESIGN.md. Do not edit. */\n";
let css = header;
for (const [theme, tokens] of Object.entries(themes)) {
  if (Object.keys(tokens).join() !== names.join())
    throw new Error("主题 Token 不一致");
  css += `${theme === "standard-light" ? ":root, " : ""}[data-theme="${theme}"] {\n`;
  for (const [key, value] of Object.entries(tokens)) {
    if (!/^#[0-9a-f]{6}([0-9a-f]{2})?$/i.test(value))
      throw new Error(`无效颜色 ${key}`);
    css += `  --ce-color-${key}: ${value};\n`;
  }
  css += "}\n";
}
const dir = resolve(root, "apps/web/src/styles");
mkdirSync(dir, { recursive: true });
writeFileSync(resolve(dir, "tokens.css"), css);
writeFileSync(
  resolve(dir, "tailwind-theme.css"),
  header +
    '@import "tailwindcss";\n@theme {\n  --color-*: initial;\n' +
    names.map((k) => `  --color-${k}: var(--ce-color-${k});`).join("\n") +
    "\n}\n",
);
console.log(
  `Generated ${names.length} semantic tokens in ${Object.keys(themes).length} themes`,
);
