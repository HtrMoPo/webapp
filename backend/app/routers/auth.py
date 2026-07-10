import asyncio
import datetime as dt
import logging

from authlib.integrations.base_client.errors import OAuthError
from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.models import RecentOAuthCallback, User
from app.zenodo_client import ZenodoClient

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger(__name__)

settings = get_settings()


def _fingerprint(value: str | None) -> str:
    """Short, non-secret stand-in for a code/state value in logs -- enough to
    tell whether two log lines refer to the same code without ever writing
    the actual (still potentially exchangeable) value to disk."""
    if not value:
        return "<none>"
    return f"{value[:6]}...(len={len(value)})"


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


# Zenodo's authorization codes are single-use: whichever request exchanges a
# given code first gets a token, and Zenodo rejects any later exchange of the
# same code with invalid_grant. Browsers routinely deliver the callback GET
# more than once for the same code -- tab/session restore, back-forward-cache
# replay, a double click on the login link, or the client retrying a GET after
# a dropped/slow response -- and without this, the *second* delivery hits
# Zenodo again and the user sees an "invalid_grant" error even though the
# first delivery already logged them in. Record the outcome per code in the
# DB (recent_oauth_callbacks) for a short window so a duplicate delivery, on
# whichever of several uvicorn workers it lands on, reuses it instead of
# re-exchanging.
_RECENT_CALLBACK_TTL_SECONDS = 120

# Zenodo's own infrastructure has, in practice, occasionally rejected the
# very first-ever exchange of a genuinely fresh code with invalid_grant
# (confirmed by request logging: no earlier delivery of the same code
# preceded it) -- consistent with the general API instability observed
# elsewhere against this same Zenodo deployment (slow/failing responses on
# otherwise-simple requests, on both the production and sandbox instances).
# A short retry of just the token POST, not the whole state-validating flow,
# sometimes gets through -- but the bad streak can run longer than a couple
# of attempts (observed: 3 retries over ~10s still failing, then succeeding
# on a fresh login's 2nd retry moments later), hence the fairly generous
# retry count here.
_TOKEN_EXCHANGE_RETRIES = 6
_TOKEN_EXCHANGE_RETRY_DELAY_SECONDS = 3


@router.get("/zenodo/login")
async def login(request: Request):
    redirect_uri = settings.zenodo_redirect_uri
    logger.info("zenodo login: redirecting to authorize (redirect_uri=%s)", redirect_uri)
    return await oauth.zenodo.authorize_redirect(request, redirect_uri)


@router.get("/zenodo/callback")
async def callback(request: Request, db: AsyncSession = Depends(get_db)):
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    error = request.query_params.get("error")
    now = dt.datetime.now(dt.timezone.utc)
    code_fp = _fingerprint(code)

    logger.info(
        "zenodo callback: received code=%s state=%s error=%s client=%s ua=%s",
        code_fp,
        _fingerprint(state),
        error,
        request.client.host if request.client else "<unknown>",
        request.headers.get("user-agent", "<none>"),
    )

    await db.execute(delete(RecentOAuthCallback).where(RecentOAuthCallback.expires_at < now))

    if code:
        cached = await db.get(RecentOAuthCallback, code)
        if cached is not None:
            age = (now - (cached.expires_at - dt.timedelta(seconds=_RECENT_CALLBACK_TTL_SECONDS))).total_seconds()
            logger.warning(
                "zenodo callback: duplicate delivery of code=%s (first seen %.1fs ago) -- reusing cached login",
                code_fp,
                age,
            )
            request.session["user_id"] = cached.user_id
            await db.commit()
            return RedirectResponse(
                url=f"{settings.url_base_path}/", headers={"Cache-Control": "no-store"}
            )

    try:
        token = await oauth.zenodo.authorize_access_token(request)
    except OAuthError as exc:
        if getattr(exc, "error", None) != "invalid_grant":
            logger.warning(
                "zenodo callback: token exchange failed for code=%s: error=%r description=%r",
                code_fp,
                getattr(exc, "error", None),
                getattr(exc, "description", None),
            )
            raise HTTPException(status_code=400, detail=f"zenodo_oauth_error: {exc}") from exc

        # authorize_access_token already validated (and cleared) state before
        # attempting the exchange, so a retry only needs to redo the token
        # POST itself -- fetch_access_token does exactly that, with no
        # session/state involvement.
        logger.warning(
            "zenodo callback: first exchange of code=%s got invalid_grant; retrying up to %d times",
            code_fp,
            _TOKEN_EXCHANGE_RETRIES,
        )
        token = None
        last_exc: Exception = exc
        for attempt in range(_TOKEN_EXCHANGE_RETRIES):
            await asyncio.sleep(_TOKEN_EXCHANGE_RETRY_DELAY_SECONDS)
            try:
                token = await oauth.zenodo.fetch_access_token(
                    code=code, redirect_uri=settings.zenodo_redirect_uri
                )
                logger.info(
                    "zenodo callback: retry %d succeeded for code=%s", attempt + 1, code_fp
                )
                break
            except Exception as retry_exc:
                last_exc = retry_exc

        if token is None:
            logger.warning(
                "zenodo callback: token exchange failed for code=%s after retries: error=%r description=%r",
                code_fp,
                getattr(last_exc, "error", None),
                getattr(last_exc, "description", None),
            )
            raise HTTPException(status_code=400, detail=f"zenodo_oauth_error: {last_exc}") from last_exc
    except Exception as exc:
        logger.exception("zenodo callback: unexpected error exchanging code=%s", code_fp)
        raise HTTPException(
            status_code=502, detail=f"zenodo_token_exchange_failed: {type(exc).__name__}: {exc}"
        ) from exc

    logger.info("zenodo callback: token exchange succeeded for code=%s", code_fp)

    zenodo_user_id = await _resolve_zenodo_user_id(token["access_token"])
    display_name = zenodo_user_id

    result = await db.execute(
        select(User).where(User.zenodo_user_id == zenodo_user_id, User.zenodo_env == settings.zenodo_env)
    )
    user = result.scalar_one_or_none()
    is_new_user = user is None

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

    await db.flush()

    if code:
        db.add(
            RecentOAuthCallback(
                code=code,
                user_id=user.id,
                expires_at=now + dt.timedelta(seconds=_RECENT_CALLBACK_TTL_SECONDS),
            )
        )

    await db.commit()
    await db.refresh(user)

    logger.info(
        "zenodo callback: login complete for code=%s user_id=%s zenodo_user_id=%s new_user=%s",
        code_fp,
        user.id,
        zenodo_user_id,
        is_new_user,
    )

    request.session["user_id"] = user.id
    return RedirectResponse(url=f"{settings.url_base_path}/", headers={"Cache-Control": "no-store"})


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
