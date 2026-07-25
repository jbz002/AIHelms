from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from core.deps import get_current_user, get_db
from exceptions import NotFoundError, UnauthorizedError
from models.auth import OAuth2CodeRequest
from services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me")
async def get_me(
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        user_info = await auth_service.get_current_user_info(
            session, current_user["id"]
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="用户不存在")
    # is_admin 优先用 JWT 动态值：SSO 用户由 app_roles 映射（oauth2_login 签 JWT 时写入），
    # DB user.is_admin 是静态默认 False。不覆盖则 SSO admin 登不进 admin 守卫。
    user_info["is_admin"] = current_user["is_admin"]
    return {"code": 200, "message": "ok", "data": user_info}


@router.post("/login/oauth2", summary="AI Hub OAuth2 登录")
async def oauth2_login(req: OAuth2CodeRequest, session: AsyncSession = Depends(get_db)):
    try:
        token, _user = await auth_service.oauth2_login(session, req.code)
    except UnauthorizedError as e:
        raise HTTPException(status_code=401, detail=str(e))
    return {
        "code": 200,
        "message": "登录成功",
        "data": {"access_token": token, "token_type": "bearer"},
    }


@router.post("/logout", summary="退出登录")
async def logout():
    # 本地 JWT 无状态，登出由前端清 token；后端仅返回成功
    return {"code": 200, "message": "已退出登录", "data": {}}
