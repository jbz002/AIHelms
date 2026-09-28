"""E2E：贡献者 Skill 上传即激活提审 + 多版本设激活（web 端真实页面流程）。

前置：后端 8000 / 前端 4002 dev server 已启动，中间件 db 运行中。
鉴权：web 仅 AI Hub SSO，agent 无法走 SSO 页面；按平台 token 规则用后端签发的
JWT 注入 localStorage（等价登录态），页面操作全部走真实 UI。

用法：PYTHONPATH=. uv run python tests/e2e_contributor_upload.py
产物：.playwright-mcp/contributor-*.png
"""

import asyncio
import io
import zipfile
from datetime import timedelta
from pathlib import Path

from playwright.async_api import async_playwright
from sqlalchemy import text

from core.database import async_session
from core.security import create_access_token
from services.auth_service import get_user_permissions

WEB_URL = "http://localhost:4002"
SHOT_DIR = Path(__file__).resolve().parents[2] / ".playwright-mcp"
ZIP_PATH = SHOT_DIR / "e2e-contributor-skill.zip"
ZIP_V2_PATH = SHOT_DIR / "e2e-contributor-skill-v2.zip"


def make_zip(path: Path, name: str, version_note: str) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            f"{name}/SKILL.md",
            f"---\nname: {name}\ndescription: e2e contribution {version_note}\n"
            f"---\n# {name}\n\ne2e body {version_note}\n",
        )
    path.write_bytes(buf.getvalue())


async def mint_token(user_id: int) -> str:
    async with async_session() as s:
        perms = await get_user_permissions(s, user_id)
    assert "skill:contribute" in perms, f"user {user_id} 无 skill:contribute 权限"
    token_data = {
        "sub": str(user_id),
        "is_admin": False,
        "permissions": perms,
    }
    return create_access_token(token_data, expires_delta=timedelta(hours=2))


async def pick_user() -> int:
    async with async_session() as s:
        result = await s.execute(
            text(
                "select u.id from aihelms.users u "
                "join aihelms.user_roles ur on ur.user_id = u.id "
                "join aihelms.roles r on r.id = ur.role_id "
                "where r.name = 'user' and u.is_admin = false order by u.id limit 1"
            )
        )
        row = result.first()
    assert row, "需至少一个持 user 角色的普通用户"
    return int(row[0])


async def cleanup(skill_name: str) -> None:
    async with async_session() as s:
        result = await s.execute(
            text("select id from aihelms.skills where name = :n"), {"n": skill_name}
        )
        row = result.first()
        if not row:
            return
        skill_id = int(row[0])
        await s.execute(
            text(
                "delete from aihelms.publish_reviews "
                "where entity_type='skill' and entity_id=:i"
            ),
            {"i": skill_id},
        )
        await s.execute(
            text("delete from aihelms.skill_versions where skill_id=:i"),
            {"i": skill_id},
        )
        await s.execute(text("delete from aihelms.skills where id=:i"), {"i": skill_id})
        await s.commit()


async def run(token: str, skill_name: str) -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(f"{WEB_URL}/login")
        await page.wait_for_load_state("networkidle")
        await page.evaluate(f"localStorage.setItem('aihelms_token', '{token}')")
        await page.goto(f"{WEB_URL}/contributor")
        await page.wait_for_load_state("networkidle")
        await page.wait_for_selector("button:has-text('新建')")
        await page.screenshot(path=str(SHOT_DIR / "contributor-upload-1-list.png"))

        # 需求 4：新建上传，无任何「设为激活」步骤
        await page.click("text=新建")
        await page.wait_for_selector("text=上传 Skill")
        await page.fill('input[placeholder="请输入 Skill 名称"]', skill_name)
        await page.set_input_files('input[type="file"]', str(ZIP_PATH))
        await page.click("button:has-text('保存')")
        await page.wait_for_selector("text=已上传并提交发布审核", timeout=15000)
        await page.wait_for_selector(f"tr:has-text('{skill_name}')")
        await page.screenshot(path=str(SHOT_DIR / "contributor-upload-2-created.png"))

        # 单版本：版本管理弹层无「设为激活」按钮
        await page.click(f"tr:has-text('{skill_name}') button[title='版本管理']")
        await page.wait_for_selector("text=已激活")
        assert (
            await page.locator("button:has-text('设为激活')").count() == 0
        ), "单版本不应出现设为激活"
        await page.screenshot(
            path=str(SHOT_DIR / "contributor-upload-3-single-version.png")
        )
        await page.mouse.click(5, 5)  # 点 backdrop 关闭弹层（弹层 @click.self）
        await page.wait_for_timeout(500)

        # 需求 4：新版本上传自动激活
        await page.click(f"tr:has-text('{skill_name}') button[title='新版本']")
        await page.wait_for_selector("text=提交新版本")
        await page.fill('input[placeholder="1.0.0"]', "1.0.1")
        await page.fill("textarea", "e2e v2")
        await page.set_input_files('input[type="file"]', str(ZIP_V2_PATH))
        await page.click("button:has-text('保存')")
        await page.wait_for_selector("text=已保存", timeout=15000)
        await page.screenshot(path=str(SHOT_DIR / "contributor-upload-4-v2-uploaded.png"))

        # 需求 3：多版本后「设为激活」出现并可切换
        await page.click(f"tr:has-text('{skill_name}') button[title='版本管理']")
        await page.wait_for_selector("button:has-text('设为激活')")

        async def accept_dialog(dialog) -> None:
            await dialog.accept()

        page.on("dialog", accept_dialog)
        await page.locator(
            "div.fixed .space-y-2 > div", has_text="v1.0.0"
        ).locator("button:has-text('设为激活')").click()
        await page.wait_for_selector("text=已设为激活版本", timeout=15000)
        await page.wait_for_timeout(500)
        await page.screenshot(path=str(SHOT_DIR / "contributor-upload-5-switched.png"))
        active_row = await page.locator(
            "div.fixed .space-y-2 > div", has_text="v1.0.0"
        ).inner_text()
        assert "已激活" in active_row, "v1.0.0 应为已激活"
        await browser.close()


async def async_main() -> None:
    skill_name = "e2e-contributor-upload"
    make_zip(ZIP_PATH, skill_name, "v1")
    make_zip(ZIP_V2_PATH, skill_name, "v2")
    await cleanup(skill_name)
    user_id = await pick_user()
    token = await mint_token(user_id)
    await run(token, skill_name)
    await cleanup(skill_name)


def main() -> None:
    SHOT_DIR.mkdir(exist_ok=True)
    asyncio.run(async_main())
    print("E2E PASS")


if __name__ == "__main__":
    main()
