// Шифрует страницы и модель для GitHub Pages.
// Пароль: переменная SITE_PASSWORD или параметр --password.
// Пароль в репозиторий не записывается.
//
// Первый запуск из папки сайта (закроет опубликованные копии):
//   SITE_PASSWORD='…' node scripts/encrypt-site.mjs
//
// Повторно зашифровать только свежий GLB и info.json
// (так делает обновить-модель.ps1, соль и пароль те же):
//   node scripts/encrypt-site.mjs --only model/apartment.glb --only model/info.json
//
// Проверка в отдельной папке, репозиторий не трогать:
//   node scripts/encrypt-site.mjs --dest /tmp/kv-preview --password '…'

import { createCipheriv, pbkdf2Sync, randomBytes } from "node:crypto";
import { copyFile, mkdir, readFile, writeFile, access } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const iterations = 600000;
const sources = [
  { logical: "index.html", bin: "index.html.bin", input: "index.html" },
  { logical: "свет.html", bin: "svet.html.bin", input: "свет.html" },
  { logical: "model/info.json", bin: "info.json.bin", input: "model/info.json" },
  { logical: "model/группы-света.json", bin: "groups.json.bin", input: "model/группы-света.json" },
  { logical: "model/apartment.glb", bin: "apartment.glb.bin", input: "model/apartment.glb" }
];

function args() {
  const out = { password: process.env.SITE_PASSWORD || "", dest: "", only: [] };
  const argv = process.argv.slice(2);
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (token === "--password") out.password = argv[++i] || "";
    else if (token === "--dest") out.dest = path.resolve(argv[++i] || "");
    else if (token === "--only") out.only.push(argv[++i] || "");
    else throw new Error("Неизвестный аргумент: " + token);
  }
  if (!out.password) {
    throw new Error("Нет пароля. Задайте SITE_PASSWORD или --password.");
  }
  return out;
}

function encrypt(plain, key) {
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", key, iv);
  const body = Buffer.concat([cipher.update(plain), cipher.final()]);
  const tag = cipher.getAuthTag();
  return Buffer.concat([iv, body, tag]);
}

async function exists(file) {
  try {
    await access(file);
    return true;
  } catch {
    return false;
  }
}

async function readManifest(dir) {
  const file = path.join(dir, "model", "crypt", "manifest.json");
  if (!(await exists(file))) return null;
  return JSON.parse(await readFile(file, "utf8"));
}

function git(argsList) {
  const result = spawnSync("git", argsList, { cwd: root, encoding: "utf8" });
  if (result.status !== 0) {
    const detail = (result.stderr || result.stdout || "").trim();
    throw new Error("git " + argsList.join(" ") + (detail ? ": " + detail : ""));
  }
}

function untrackPlaintext() {
  for (const file of ["model/apartment.glb", "model/info.json", "model/группы-света.json"]) {
    const listed = spawnSync("git", ["ls-files", "--error-unmatch", "--", file], { cwd: root, encoding: "utf8" });
    if (listed.status !== 0) continue;
    git(["rm", "--cached", "-f", "--", file]);
  }
}

async function main() {
  const options = args();
  const destRoot = options.dest || root;
  const inPlace = !options.dest;
  const cryptDir = path.join(destRoot, "model", "crypt");
  await mkdir(cryptDir, { recursive: true });
  await mkdir(path.join(destRoot, "scripts"), { recursive: true });

  const previous = await readManifest(destRoot);
  const salt = previous ? Buffer.from(previous.salt, "base64") : randomBytes(16);
  const key = pbkdf2Sync(options.password, salt, iterations, 32, "sha256");

  if (previous) {
    const probe = path.join(destRoot, "model", "crypt", "info.json.bin");
    if (await exists(probe)) {
      const { createDecipheriv } = await import("node:crypto");
      const packed = await readFile(probe);
      const iv = packed.subarray(0, 12);
      const tag = packed.subarray(packed.length - 16);
      const body = packed.subarray(12, packed.length - 16);
      const decipher = createDecipheriv("aes-256-gcm", key, iv);
      decipher.setAuthTag(tag);
      try {
        Buffer.concat([decipher.update(body), decipher.final()]);
      } catch {
        throw new Error("Пароль не подходит к уже зашифрованному сайту.");
      }
    }
  }

  const chosen = options.only.length
    ? sources.filter((item) => options.only.includes(item.logical))
    : sources;
  if (!chosen.length) throw new Error("Нечего шифровать.");

  const siteSrc = path.join(root, "site-src");
  if (inPlace && !options.only.length) {
    await mkdir(siteSrc, { recursive: true });
    for (const item of sources) {
      const from = path.join(root, item.input);
      const gate = item.input.endsWith(".html") && (await readFile(from, "utf8")).includes("kvartira-gate");
      const backup = path.join(siteSrc, item.input);
      if (!gate && await exists(from) && !(await exists(backup))) {
        await mkdir(path.dirname(backup), { recursive: true });
        await copyFile(from, backup);
      }
    }
  }

  async function plainPath(item) {
    const backup = path.join(siteSrc, item.input);
    if (item.input.endsWith(".html") && await exists(backup)) return backup;
    if (item.input.endsWith(".json") && inPlace && await exists(backup) && options.only.length) return backup;
    return path.join(root, item.input);
  }

  for (const item of chosen) {
    const file = await plainPath(item);
    const plain = await readFile(file);
    await writeFile(path.join(cryptDir, item.bin), encrypt(plain, key));
    process.stdout.write("зашифрован " + item.logical + " (" + plain.length + " байт)\n");
  }

  const manifest = {
    v: 1,
    kdf: "PBKDF2-SHA256",
    iterations,
    salt: salt.toString("base64"),
    files: Object.fromEntries(sources.map((item) => [item.logical, item.bin]))
  };
  await writeFile(path.join(cryptDir, "manifest.json"), JSON.stringify(manifest, null, 2) + "\n");

  if (!options.only.length) {
    const template = await readFile(path.join(root, "scripts", "gate.html"), "utf8");
    await writeFile(path.join(destRoot, "index.html"), template.replaceAll("__PAGE_ID__", "index"));
    await writeFile(path.join(destRoot, "свет.html"), template.replaceAll("__PAGE_ID__", "svet"));
    await copyFile(path.join(root, "sw.js"), path.join(destRoot, "sw.js"));
  }

  if (inPlace && !options.only.length) {
    const ignorePath = path.join(root, ".gitignore");
    const ignore = await readFile(ignorePath, "utf8");
    const extra = ["site-src/", "model/apartment.glb", "model/info.json", "model/группы-света.json"];
    const missing = extra.filter((line) => !ignore.split(/\r?\n/).includes(line));
    if (missing.length) await writeFile(ignorePath, ignore.replace(/\s*$/, "\n") + missing.join("\n") + "\n");
    untrackPlaintext();
    process.stdout.write("Открытые копии сняты с учёта git и больше не коммитятся. Сам коммит скрипт не делает.\n");
  }
}

main().catch((error) => {
  process.stderr.write(String(error.message || error) + "\n");
  process.exit(1);
});
