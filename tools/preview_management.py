"""Local UI QA with real plugin services, isolated data and a simulated model.

Run: python -B tools/preview_management.py --port 8766
No QQ messages, deployment data, or real model requests are involved.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
import threading
import types
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from test_main import _Context, _Event, _load_main_module

BRIDGE = """
window.AstrBotPluginPage = {
 ready: async()=>({isDark:false}),
 apiGet: async(path,params={})=>call(path,'GET',params),
 apiPost: async(path,body)=>call(path,'POST',body),
 download: async(path,params={},filename='数字卦卦例库.zip')=>{
  const response=await fetch('/__api/'+path+'?'+new URLSearchParams(params));
  if(!response.ok)throw new Error('下载失败');
  const url=URL.createObjectURL(await response.blob());
  const a=document.createElement('a');a.href=url;a.download=filename;a.click();
  setTimeout(()=>URL.revokeObjectURL(url),10000);return {filename};
 }
};
async function call(path,method,data){
 const query=method==='GET'?'?'+new URLSearchParams(data):'';
 const response=await fetch('/__api/'+path+query,{method,
  headers:{'Content-Type':'application/json'},body:method==='POST'?JSON.stringify(data):undefined});
 const result=await response.json();if(!response.ok)throw new Error(result.error||'请求失败');return result;
}
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument(
        "--rank-samples", action="store_true", help="Seed simulated token ranking cases"
    )
    args = parser.parse_args()
    sandbox = Path(tempfile.mkdtemp(prefix="wuxing-page-preview-"))
    module = _load_main_module()
    module.DATA_DIR, module.STATE_FILE = sandbox, sandbox / "dead_streaks.json"

    class Config(dict):
        def save_config(self, values):
            self.update(values)
            (sandbox / "settings.json").write_text(
                json.dumps(values, ensure_ascii=False), encoding="utf-8"
            )

    class Context(_Context):
        def get_all_providers(self):
            return [
                types.SimpleNamespace(provider_config={"id": "offline-preview-model"})
            ]

        async def llm_generate(self, **kwargs):
            return types.SimpleNamespace(
                role="assistant",
                completion_text="【离线模拟 AI，仅供页面验收】程序已经给出独立判定。请结合逐轮过程与资料约定复核；应期单位未定，不应当作实际日期。",
                usage=types.SimpleNamespace(
                    input_other=240, input_cached=80, output=96
                ),
            )

    plugin = module.WuxingNumberDivinationPlugin(
        Context(),
        Config(kernel_id="legacy_v1", page_provider_id="offline-preview-model"),
    )
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()

    async def seed():
        if args.rank_samples:
            # Deliberately different count/token orders; all identities and usage
            # are synthetic and confined to this preview's temporary directory.
            samples = (
                [(0, 0, 0)] * 5
                + [
                    (1, 1, 24000),
                    (2, 2, 8000),
                    (1, 2, 3000),
                    (1, 1, None),
                    (2, 2, "old"),
                ]
                + [(3, 3, None)] * 4
                + [(4, 4, "old")] * 2
            )
            result = module.calculate(
                "模拟排行验收事项能否达成", "15997", "水", kernel_id="document_v2"
            )
            for i, (user, group, total) in enumerate(samples):
                identity = {
                    "id": f"{i:024x}",
                    "source": "command",
                    "platform": "offline-preview",
                    "user_id": str(10000 + user),
                    "user_name": f"模拟问卦人 {user}",
                    "group_id": str(20000 + group),
                    "group_name": f"模拟群 {group}",
                    "ai_used": total != 0,
                    "ai_status": "not_requested",
                    "ai_interpretation": "",
                    "ai_error": "",
                    "root_source": "手动指定" if total == 0 else "AI 按问题选取",
                }
                if total != "old":
                    identity["token_usage"] = module.usage_snapshot(
                        scope="agent_context"
                        if total is None
                        else "local"
                        if total == 0
                        else "root_selection",
                        response=types.SimpleNamespace(
                            usage={
                                "input_tokens": total - 100,
                                "output_tokens": 100,
                                "total_tokens": total,
                            }
                        )
                        if total
                        else None,
                        provider_id="offline-preview-model" if total else "",
                    )
                await asyncio.to_thread(
                    plugin._get_case_store().add,
                    plugin._case_record(
                        result,
                        "模拟排行验收事项能否达成",
                        module.build_reading(result),
                        identity,
                    ),
                )
            return
        for i in range(25):
            event = _Event(
                sender_id=str(10000 + i % 4),
                group_id=str(20000 + i % 3),
                message_id=f"preview-{i}",
            )
            result = module.calculate(
                "模拟交易事项能否达成", "15997", "水", kernel_id="document_v2"
            )
            await plugin._record_cast(
                event,
                result,
                "模拟交易事项能否达成",
                module.build_reading(result),
                "command",
                "手动指定",
            )

    asyncio.run_coroutine_threadsafe(seed(), loop).result()

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(ROOT / "pages/manage"), **kwargs)

        def send_content(self, content, content_type="application/json", code=200):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/__preview_bridge.js":
                return self.send_content(
                    BRIDGE.encode(), "text/javascript; charset=utf-8"
                )
            if path.startswith("/__api/"):
                return self.api("GET")
            if path in ("/", "/index.html"):
                html = (ROOT / "pages/manage/index.html").read_text("utf-8")
                html = html.replace(
                    '<script type="module"',
                    '<script src="/__preview_bridge.js"></script><script type="module"',
                    1,
                )
                return self.send_content(html.encode(), "text/html; charset=utf-8")
            return super().do_GET()

        def do_POST(self):
            if not urlsplit(self.path).path.startswith("/__api/"):
                return self.send_error(404)
            return self.api("POST")

        def api(self, method):
            parsed = urlsplit(self.path)
            path = parsed.path.removeprefix("/__api/")
            try:
                payload = (
                    json.loads(
                        self.rfile.read(int(self.headers.get("Content-Length", "0")))
                    )
                    if method == "POST"
                    else {k: v[0] for k, v in parse_qs(parsed.query).items()}
                )
                kwargs = {"username": "离线验收管理员"}
                action = {
                    ("settings", "GET"): plugin.page_settings,
                    ("settings", "POST"): plugin.page_save_settings,
                    ("test", "POST"): plugin.page_test,
                    ("stats", "GET"): plugin.page_stats,
                    ("history", "GET"): plugin.page_history,
                    ("export", "GET"): plugin.page_export,
                }.get((path, method))
                if path.startswith("history/") and path.endswith("/preview"):
                    action, kwargs["record_id"] = (
                        plugin.page_preview,
                        path.split("/")[1],
                    )
                if action is None:
                    return self.send_error(404)
                result = asyncio.run_coroutine_threadsafe(
                    action(payload, **kwargs), loop
                ).result(timeout=190)
                if isinstance(result, Path):
                    return self.send_content(result.read_bytes(), "application/zip")
                return self.send_content(
                    json.dumps(result, ensure_ascii=False).encode()
                )
            except Exception as exc:  # noqa: BLE001 - isolated development harness error response.
                return self.send_content(
                    json.dumps({"error": str(exc)}, ensure_ascii=False).encode(),
                    code=400,
                )

    print(
        f"Local preview: http://127.0.0.1:{args.port} | isolated data: {sandbox}",
        flush=True,
    )
    try:
        ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
    finally:
        loop.call_soon_threadsafe(loop.stop)


if __name__ == "__main__":
    main()
