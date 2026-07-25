from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.deps import get_current_user, get_db
from exceptions import NotFoundError, UnauthorizedError
from models.auth import ChangePasswordRequest, LoginRequest, OAuth2CodeRequest
from services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", summary="用户登录")
async def login(
    req: LoginRequest, request: Request, session: AsyncSession = Depends(get_db)
):
    try:
        token, user = await auth_service.login(session, req.username, req.password)
    except UnauthorizedError as e:
        raise HTTPException(status_code=401, detail=str(e))
    request.state.current_user = {
        "id": user.id,
        "username": user.username,
        "is_admin": user.is_admin,
    }
    return {
        "code": 200,
        "message": "登录成功",
        "data": {"access_token": token, "token_type": "bearer"},
    }


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


@router.put("/password", summary="修改密码")
async def change_password(
    req: ChangePasswordRequest,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        await auth_service.change_password(
            session, current_user["id"], req.old_password, req.new_password
        )
    except UnauthorizedError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"code": 200, "message": "密码修改成功", "data": None}
