// Восстанавливает site-src из зашифрованных файлов. Пароль: SITE_PASSWORD или --password.
//   SITE_PASSWORD='…' node scripts/decrypt-site.mjs

import { createDecipheriv, pbkdf2Sync } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const outputs = {
  "index.html.bin": "index.html",
  "svet.html.bin": "свет.html",
  "info.json.bin": "model/info.json",
  "groups.json.bin": "model/группы-света.json",
  "apartment.glb.bin": "model/apartment.glb"
};

function password() {
  const argv = process.argv.slice(2);
  const flag = argv.indexOf("--password");
  const value = process.env.SITE_PASSWORD || (flag >= 0 ? argv[flag + 1] : "");
  if (!value) throw new Error("Нет пароля. Задайте SITE_PASSWORD или --password.");
  return value;
}

function decrypt(packed, key) {
  const iv = packed.subarray(0, 12);
  const tag = packed.subarray(packed.length - 16);
  const body = packed.subarray(12, packed.length - 16);
  const decipher = createDecipheriv("aes-256-gcm", key, iv);
  decipher.setAuthTag(tag);
  return Buffer.concat([decipher.update(body), decipher.final()]);
}

const manifest = JSON.parse(await readFile(path.join(root, "model", "crypt", "manifest.json"), "utf8"));
const key = pbkdf2Sync(password(), Buffer.from(manifest.salt, "base64"), manifest.iterations, 32, "sha256");
for (const [bin, target] of Object.entries(outputs)) {
  const packed = await readFile(path.join(root, "model", "crypt", bin));
  const plain = decrypt(packed, key);
  const file = path.join(root, "site-src", target);
  await mkdir(path.dirname(file), { recursive: true });
  await writeFile(file, plain);
  process.stdout.write("восстановлен site-src/" + target + "\n");
}
