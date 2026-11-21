// firmware-worker.js - runs firmware-core.js off the page's main thread (the compression takes 10-30 s).
// Messages in:  { stock: ArrayBuffer, build: "nam" | "amps" | "full" }   (recipe-<build>.bin, tools/recipe.py)
// Messages out: { type: "progress", step } | { type: "done", bytes: ArrayBuffer, md5 } | { type: "error", code }
importScripts(
  "https://cdnjs.cloudflare.com/ajax/libs/pako/2.1.0/pako.min.js",
  "https://cdnjs.cloudflare.com/ajax/libs/spark-md5/3.0.2/spark-md5.min.js",
  "firmware-core.js"
);

function md5(u8) {
  return SparkMD5.ArrayBuffer.hash(u8.buffer.slice(u8.byteOffset, u8.byteOffset + u8.byteLength));
}

onmessage = function (e) {
  var name = "recipe-" + e.data.build + ".bin";
  fetch(name, { cache: "no-cache" }).then(function (r) {
    if (!r.ok) throw new Error(name + ": HTTP " + r.status);
    return r.arrayBuffer();
  }).then(function (recipe) {
    var names = ["read", "check", "apply", "compress", "pack", "done"];
    var out = FIRMWARE.build(new Uint8Array(e.data.stock), new Uint8Array(recipe), {
      pako: pako, md5: md5,
      progress: function (s) { postMessage({ type: "progress", step: names.indexOf(s) + 1 }); }
    });
    var buf = out.hxf.buffer.slice(out.hxf.byteOffset, out.hxf.byteOffset + out.hxf.byteLength);
    postMessage({ type: "done", bytes: buf, md5: out.md5 }, [buf]);
  }).catch(function (err) {
    postMessage({ type: "error", code: err.message });
  });
};
