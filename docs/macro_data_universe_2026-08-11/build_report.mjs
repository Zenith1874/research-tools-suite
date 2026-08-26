#!/usr/bin/env node

import {
  mkdirSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const REPORT_DIRECTORY = dirname(fileURLToPath(import.meta.url));
const OVERFLOW_FIX = `<style data-macro-universe-portable-overflow-fix="true">
@media screen {
  html body #data-analytics-portable-reader .analytics-top-bar,
  html body #data-analytics-portable-fallback .portable-page-header {
    width: 100% !important;
    margin-right: 0 !important;
    margin-left: 0 !important;
  }
}
</style>`;

function usage() {
  return [
    "Usage: node build_report.mjs --plugin-root <data-analytics-plugin-root> [options]",
    "",
    "Options:",
    "  --artifact <artifact.json>  Canonical report artifact input.",
    "  --output <report.html>      Self-contained portable HTML output.",
  ].join("\n");
}

function parseArguments(arguments_) {
  const options = {};
  for (let index = 0; index < arguments_.length; index += 1) {
    const argument = arguments_[index];
    if (argument === "--help" || argument === "-h") return { help: true };
    if (!argument.startsWith("--")) throw new Error(`Unexpected argument: ${argument}`);
    const key = argument.slice(2);
    if (!["artifact", "output", "plugin-root"].includes(key)) {
      throw new Error(`Unknown option: ${argument}`);
    }
    const value = arguments_[index + 1];
    if (!value || value.startsWith("--")) throw new Error(`Missing value for ${argument}`);
    options[key] = value;
    index += 1;
  }
  return options;
}

function addOverflowFix(html) {
  const anchor = '<style data-data-analytics-portable-fallback="true">';
  if (html.includes(OVERFLOW_FIX)) return html;
  if (!html.includes(anchor)) throw new Error("Portable fallback style anchor was not found.");
  return html.replace(anchor, `${OVERFLOW_FIX}\n${anchor}`);
}

async function main() {
  const options = parseArguments(process.argv.slice(2));
  if (options.help) {
    console.log(usage());
    return;
  }
  if (!options["plugin-root"]) throw new Error(`--plugin-root is required.\n${usage()}`);

  const pluginRoot = resolve(options["plugin-root"]);
  const artifactPath = resolve(options.artifact ?? join(REPORT_DIRECTORY, "artifact.json"));
  const outputPath = resolve(options.output ?? join(REPORT_DIRECTORY, "report.html"));
  const scriptRoot = join(pluginRoot, "skills", "build-report", "scripts");

  const { buildPortableArtifact } = await import(
    pathToFileURL(join(scriptRoot, "build_portable_artifact.mjs")).href
  );
  const { extractPortableChartSvgs } = await import(
    pathToFileURL(join(scriptRoot, "extract_portable_chart_svgs.mjs")).href
  );
  const { verifyPortableArtifact } = await import(
    pathToFileURL(join(scriptRoot, "verify_portable_artifact.mjs")).href
  );

  const artifact = JSON.parse(readFileSync(artifactPath, "utf8"));
  mkdirSync(dirname(outputPath), { recursive: true });

  let html = buildPortableArtifact(artifact);
  writeFileSync(outputPath, html, "utf8");
  const staticCharts = await extractPortableChartSvgs({ htmlPath: outputPath });
  html = addOverflowFix(buildPortableArtifact(artifact, { staticCharts }));
  writeFileSync(outputPath, html, "utf8");

  const verification = await verifyPortableArtifact({
    artifactPath,
    htmlPath: outputPath,
  });
  console.log(JSON.stringify({
    artifact: artifactPath,
    charts: Object.keys(staticCharts),
    output: outputPath,
    pluginRoot,
    verification,
  }));
}

main().catch((error) => {
  console.error(error?.stack ?? String(error));
  process.exitCode = 1;
});
