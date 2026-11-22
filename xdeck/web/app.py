"""ボードの Web サーバー(aiohttp)の組み立て。"""
from pathlib import Path

from aiohttp import web

from ..config import ENT, GALLERY_URL, PORT, PORT_ENT, PORT_ADULT
from ..services import discord_link, status
from . import routes_accounts, routes_routine, routes_schedule, routes_works

STATIC_DIR = Path(__file__).parent / "static"


def favicon_svg() -> str:
    c1, c2 = ("#ff8a5c", "#e0357a") if ENT else ("#4a82f2", "#1d4fd0")  # アダルト=青 / エンタメ=オレンジ〜ピンク
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="100 100 824 824"><defs>'
            f'<linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{c1}"/>'
            f'<stop offset="1" stop-color="{c2}"/></linearGradient></defs>'
            '<rect x="100" y="100" width="824" height="824" rx="184" fill="url(#g)"/>'
            '<rect x="240" y="240" width="250" height="330" rx="44" fill="#fff"/>'
            '<rect x="534" y="240" width="250" height="196" rx="44" fill="#fff" fill-opacity=".92"/>'
            '<rect x="534" y="480" width="250" height="90" rx="40" fill="#fff" fill-opacity=".75"/>'
            '<rect x="240" y="614" width="544" height="170" rx="44" fill="#fff" fill-opacity=".6"/></svg>')


def page() -> str:
    """index.html のプレースホルダ(ボード名・ポート・現在のボード)を埋めて返す"""
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    html = html.replace("__BN__", "(エンタメ)" if ENT else "").replace("__ENT__", "true" if ENT else "false")
    cur = 'aria-current="page"'
    return (html.replace("__P_A__", PORT_ADULT).replace("__P_E__", PORT_ENT)
            .replace("__A_A__", "" if ENT else cur).replace("__A_E__", cur if ENT else ""))


async def index(_):
    return web.Response(text=page(), content_type="text/html")


async def favicon(_):
    return web.Response(text=favicon_svg(), content_type="image/svg+xml")


async def api_discord(_):
    """サイドバーの「Discordを開く」の飛び先(Bot の接続前は空)"""
    return web.json_response({"url": discord_link.get_url()})


async def api_status(_):
    """右上の接続表示用: Discord Bot と Xdeck の接続状態"""
    return web.json_response({"discord": status.discord_state(), "xdeck": await status.xdeck_state()})


@web.middleware
async def _local_only(req: web.Request, handler):
    """ほかのサイトのページからボードを操作されないようにする(Host/Origin が自分のボードのときだけ通す)"""
    hosts = {f"localhost:{PORT}", f"127.0.0.1:{PORT}"}
    if req.host not in hosts:  # DNSリバインディング対策
        raise web.HTTPForbidden(text="forbidden host")
    origin = req.headers.get("Origin")
    if req.method not in ("GET", "HEAD") and origin and origin.removeprefix("http://") not in hosts:
        raise web.HTTPForbidden(text="forbidden origin")
    return await handler(req)


async def _no_stale_static(req: web.Request, resp: web.StreamResponse) -> None:
    """画面ファイル(css/js)を更新したあと、ブラウザに古い版を使わせない(毎回、更新の有無を確認させる)"""
    if req.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache"


async def start_web() -> None:
    app = web.Application(middlewares=[_local_only])
    app.on_response_prepare.append(_no_stale_static)
    app.add_routes([web.get("/", index), web.get("/favicon.svg", favicon), web.get("/favicon.ico", favicon),
                    web.get("/api/discord", api_discord), web.get("/api/status", api_status)])
    app.add_routes(routes_works.routes)
    app.add_routes(routes_schedule.routes)
    app.add_routes(routes_routine.routes)
    app.add_routes(routes_accounts.routes)
    app.router.add_static("/static", STATIC_DIR)
    runner = web.AppRunner(app)
    await runner.setup()
    # コピー系は操作を伴うので自分のMacからのみ受け付ける
    await web.TCPSite(runner, "127.0.0.1", PORT).start()
    print(f"gallery: {GALLERY_URL}")
