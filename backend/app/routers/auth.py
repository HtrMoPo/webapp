import datetime as dt

from authlib.integrations.base_client.errors import OAuthError
from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.models import User
from app.zenodo_client import ZenodoClient

router = APIRouter(prefix="/api/auth", tags=["auth"])

settings = get_settings()

oauth = OAuth()
oauth.register(
    name="zenodo",
    client_id=settings.zenodo_client_id,
    client_secret=settings.zenodo_client_secret,
    access_token_url=f"{settings.zenodo_base_url}/oauth/token",
    authorize_url=f"{settings.zenodo_base_url}/oauth/authorize",
    # Zenodo's Invenio-based OAuth provider expects client credentials in the
    # token request body, not an HTTP Basic auth header (authlib's default).
    token_endpoint_auth_method="client_secret_post",
    client_kwargs={"scope": "deposit:write deposit:actions"},
)


@router.get("/zenodo/login")
async def login(request: Request):
    redirect_uri = settings.zenodo_redirect_uri
    return await oauth.zenodo.authorize_redirect(request, redirect_uri)


@router.get("/zenodo/callback")
async def callback(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        token = await oauth.zenodo.authorize_access_token(request)
    except OAuthError as exc:
        raise HTTPException(status_code=400, detail=f"zenodo_oauth_error: {exc}") from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"zenodo_token_exchange_failed: {type(exc).__name__}: {exc}"
        ) from exc

    zenodo_user_id = await _resolve_zenodo_user_id(token["access_token"])
    display_name = zenodo_user_id

    result = await db.execute(
        select(User).where(User.zenodo_user_id == zenodo_user_id, User.zenodo_env == settings.zenodo_env)
    )
    user = result.scalar_one_or_none()

    expires_at = None
    if "expires_at" in token:
        expires_at = dt.datetime.fromtimestamp(token["expires_at"], tz=dt.timezone.utc)

    if user is None:
        user = User(
            zenodo_user_id=zenodo_user_id,
            zenodo_env=settings.zenodo_env,
            display_name=display_name,
            access_token=token["access_token"],
            refresh_token=token.get("refresh_token"),
            token_expires_at=expires_at,
        )
        db.add(user)
    else:
        user.display_name = display_name
        user.access_token = token["access_token"]
        user.refresh_token = token.get("refresh_token") or user.refresh_token
        user.token_expires_at = expires_at

    await db.commit()
    await db.refresh(user)

    request.session["user_id"] = user.id
    return RedirectResponse(url=f"{settings.url_base_path}/")


async def _resolve_zenodo_user_id(access_token: str) -> str:
    """Zenodo's deposit API has no OIDC userinfo endpoint reachable with
    deposit:write/deposit:actions scopes, but every deposition it returns is
    tagged with its owner's numeric user id. We create a throwaway deposition,
    read its owner id, and immediately discard it to identify the user."""
    client = ZenodoClient(get_settings().zenodo_api_url, access_token)
    deposition = await client.create_deposition()
    owner = deposition.raw.get("owners") or deposition.raw.get("owner")
    owner_id = owner[0] if isinstance(owner, list) else owner
    await client.discard(deposition.id)
    return str(owner_id)


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@router.get("/me")
async def me(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        return {"authenticated": False}
    user = await db.get(User, user_id)
    if not user:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "display_name": user.display_name,
        "zenodo_env": user.zenodo_env,
        "is_admin": user.is_admin,
    }
