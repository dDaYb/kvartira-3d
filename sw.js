/* Расшифровка страниц и модели после ввода пароля. Сам ключ сюда не записан. */
const FILES = {
  "index.html": { bin: "model/crypt/index.html.bin", type: "text/html; charset=utf-8" },
  "свет.html": { bin: "model/crypt/svet.html.bin", type: "text/html; charset=utf-8" },
  "model/info.json": { bin: "model/crypt/info.json.bin", type: "application/json; charset=utf-8" },
  "model/группы-света.json": { bin: "model/crypt/groups.json.bin", type: "application/json; charset=utf-8" },
  "model/apartment.glb": { bin: "model/crypt/apartment.glb.bin", type: "model/gltf-binary" }
};

let cryptoKey = null;
const memory = new Map();

self.addEventListener("install", (event) => {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("message", (event) => {
  const reply = (body) => {
    if (event.ports && event.ports[0]) event.ports[0].postMessage(body);
  };
  if (!event.data || event.data.type !== "unlock") {
    reply({ ok: false });
    return;
  }
  crypto.subtle.importKey("raw", event.data.rawKey, { name: "AES-GCM" }, false, ["decrypt"])
    .then((key) => {
      cryptoKey = key;
      memory.clear();
      reply({ ok: true });
    })
    .catch((error) => reply({ ok: false, error: String(error) }));
});

function relativePath(url) {
  const scope = new URL(self.registration.scope);
  const path = decodeURIComponent(url.pathname);
  const base = scope.pathname;
  const rel = path.startsWith(base) ? path.slice(base.length) : path.replace(/^\//, "");
  if (rel === "" || rel === "index.html") return "index.html";
  return rel;
}

async function decryptBin(binPath) {
  if (memory.has(binPath)) return memory.get(binPath);
  const response = await fetch(new URL(binPath, self.registration.scope), { cache: "no-store" });
  if (!response.ok) throw new Error(binPath + " " + response.status);
  const bytes = new Uint8Array(await response.arrayBuffer());
  if (bytes.length < 12 + 16) throw new Error("короткий файл " + binPath);
  const iv = bytes.slice(0, 12);
  const data = bytes.slice(12);
  const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv, tagLength: 128 }, cryptoKey, data);
  memory.set(binPath, plain);
  return plain;
}

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;
  const rel = relativePath(url);
  const file = FILES[rel];
  if (!file) return;
  if (!cryptoKey) {
    if (rel === "index.html" || rel === "свет.html") return;
    event.respondWith(new Response("Нужен пароль.", { status: 401, headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" } }));
    return;
  }
  event.respondWith((async () => {
    const plain = await decryptBin(file.bin);
    return new Response(plain, {
      status: 200,
      headers: { "content-type": file.type, "cache-control": "no-store" }
    });
  })());
});
