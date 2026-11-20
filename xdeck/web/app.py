"""ボードの Web サーバー(aiohttp)の組み立て。"""
from pathlib import Path

from aiohttp import web

from ..config import ENT, GALLERY_URL, PORT, PORT_ENT, PORT_NORMAL
from . import routes_accounts, routes_schedule, routes_works

STATIC_DIR = Path(__file__).parent / "static"


def favicon_svg() -> str:
    c1, c2 = ("#ff8a5c", "#e0357a") if ENT else ("#4a82f2", "#1d4fd0")  # 普通=青 / エンタメ=オレンジ〜ピンク
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
    return (html.replace("__P_N__", PORT_NORMAL).replace("__P_E__", PORT_ENT)
            .replace("__A_N__", "" if ENT else cur).replace("__A_E__", cur if ENT else ""))


async def index(_):
    return web.Response(text=page(), content_type="text/html")


async def favicon(_):
    return web.Response(text=favicon_svg(), content_type="image/svg+xml")


async def start_web() -> None:
    app = web.Application()
    app.add_routes([web.get("/", index), web.get("/favicon.svg", favicon), web.get("/favicon.ico", favicon)])
    app.add_routes(routes_works.routes)
    app.add_routes(routes_schedule.routes)
    app.add_routes(routes_accounts.routes)
    app.router.add_static("/static", STATIC_DIR)
    runner = web.AppRunner(app)
    await runner.setup()
    # コピー系は操作を伴うので自分のMacからのみ受け付ける
    await web.TCPSite(runner, "127.0.0.1", PORT).start()
    print(f"gallery: {GALLERY_URL}")
