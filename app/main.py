from __future__ import annotations

from datetime import date
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from app.config import SecuritySettings, load_security_settings
from app.database import get_session, init_db
from app.schemas import (
    BuyRequest,
    CashflowRequest,
    DuplicateCheckRequest,
    EventUpdateRequest,
    LotSLUpdateRequest,
    ReviewRequest,
    SellRequest,
)
from app.security import (
    clear_admin_failed_attempts,
    check_admin_rate_limit,
    clear_session_cookie,
    create_session_token,
    get_current_role,
    is_valid_admin_token,
    is_valid_viewer_token,
    register_admin_failed_attempt,
    require_admin_api,
    require_viewer_api,
    set_session_cookie,
    verify_admin_password,
)
from app.services import (
    backup_database,
    build_benchmark_returns,
    build_fx_history,
    build_journal,
    build_portfolio,
    build_stats,
    build_trade_detail,
    create_buy,
    create_cashflow,
    create_review,
    create_sell,
    check_duplicate_event,
    delete_event,
    export_events_csv,
    export_lots_csv,
    export_sell_allocations_csv,
    get_market_data_cache_status,
    refresh_market_data_cache,
    save_uploaded_image,
    update_event,
    update_lot_sl,
)

security_settings: SecuritySettings = load_security_settings()

app = FastAPI(
    title="Trade Journal & Portfolio",
    docs_url="/docs" if security_settings.docs_enabled else None,
    redoc_url="/redoc" if security_settings.docs_enabled else None,
    openapi_url="/openapi.json" if security_settings.docs_enabled else None,
)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount("/uploads", StaticFiles(directory="data/uploads", check_dir=False), name="uploads")
templates = Jinja2Templates(directory="app/templates")

viewer_api_guard = require_viewer_api(security_settings)
admin_api_guard = require_admin_api(security_settings)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


def _commit_with_backup(session: Session) -> str | None:
    session.commit()
    return backup_database()


def _journal_page_url(
    page: int,
    q: str | None,
    event_type: str | None,
    date_from: date | None,
    date_to: date | None,
    hf_ticker: list[str] | None = None,
    hf_market: list[str] | None = None,
    hf_currency: list[str] | None = None,
    hf_symbol_name: list[str] | None = None,
    hf_type: list[str] | None = None,
    hf_win_lose: list[str] | None = None,
) -> str:
    params: dict[str, str | int | list[str]] = {"page": page}
    if q:
        params["q"] = q
    if event_type:
        params["event_type"] = event_type
    if date_from:
        params["date_from"] = date_from.isoformat()
    if date_to:
        params["date_to"] = date_to.isoformat()
    if hf_ticker:
        params["hf_ticker"] = hf_ticker
    if hf_market:
        params["hf_market"] = hf_market
    if hf_currency:
        params["hf_currency"] = hf_currency
    if hf_symbol_name:
        params["hf_symbol_name"] = hf_symbol_name
    if hf_type:
        params["hf_type"] = hf_type
    if hf_win_lose:
        params["hf_win_lose"] = hf_win_lose
    return f"/journal?{urlencode(params, doseq=True)}"


def _template_auth_context(request: Request) -> dict[str, str | bool | None]:
    role = get_current_role(request, security_settings)
    return {
        "auth_role": role,
        "can_write": role == "admin",
    }


def _require_viewer_page_role(request: Request) -> str | None:
    role = get_current_role(request, security_settings)
    if role in ("viewer", "admin"):
        return role
    return None


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/journal")


@app.get("/access", response_class=HTMLResponse)
def access_required_page(request: Request) -> HTMLResponse:
    role = get_current_role(request, security_settings)
    return templates.TemplateResponse(
        "access_required.html",
        {
            "request": request,
            "auth_role": role,
            "can_write": role == "admin",
        },
    )


@app.get("/access/view/{viewer_token}")
def access_viewer(viewer_token: str) -> RedirectResponse:
    if not is_valid_viewer_token(viewer_token, security_settings):
        raise HTTPException(status_code=404, detail="Not found")

    token, expires_at = create_session_token("viewer", security_settings)
    response = RedirectResponse(url="/journal", status_code=303)
    set_session_cookie(response, token, expires_at)
    return response


@app.get("/access/admin/{admin_token}", response_class=HTMLResponse)
def access_admin_form(
    request: Request,
    admin_token: str,
    error: str | None = Query(default=None),
) -> HTMLResponse:
    if not is_valid_admin_token(admin_token, security_settings):
        raise HTTPException(status_code=404, detail="Not found")

    role = get_current_role(request, security_settings)
    return templates.TemplateResponse(
        "access_admin.html",
        {
            "request": request,
            "token": admin_token,
            "error": error,
            "auth_role": role,
            "can_write": role == "admin",
        },
    )


@app.post("/access/admin/{admin_token}/unlock", response_class=HTMLResponse)
def access_admin_unlock(
    request: Request,
    admin_token: str,
    password: str = Form(...),
) -> Response:
    if not is_valid_admin_token(admin_token, security_settings):
        raise HTTPException(status_code=404, detail="Not found")

    try:
        check_admin_rate_limit(request)
    except HTTPException as exc:
        return templates.TemplateResponse(
            "access_admin.html",
            {
                "request": request,
                "token": admin_token,
                "error": exc.detail,
                **_template_auth_context(request),
            },
            status_code=exc.status_code,
        )

    if not verify_admin_password(password, security_settings):
        register_admin_failed_attempt(request)
        return templates.TemplateResponse(
            "access_admin.html",
            {
                "request": request,
                "token": admin_token,
                "error": "Invalid password",
                **_template_auth_context(request),
            },
            status_code=401,
        )

    clear_admin_failed_attempts(request)
    token, expires_at = create_session_token("admin", security_settings)
    response = RedirectResponse(url="/journal", status_code=303)
    set_session_cookie(response, token, expires_at)
    return response


@app.post("/logout")
def logout() -> RedirectResponse:
    response = RedirectResponse(url="/access", status_code=303)
    clear_session_cookie(response)
    return response


@app.post("/api/buy")
def api_buy(
    payload: BuyRequest,
    _auth: str = Depends(admin_api_guard),
    session: Session = Depends(get_session),
) -> dict:
    try:
        result = create_buy(session, payload)
        backup_path = _commit_with_backup(session)
        return {"ok": True, **result, "backup": backup_path}
    except HTTPException:
        session.rollback()
        raise
    except Exception as exc:  # pragma: no cover
        session.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/sell")
def api_sell(
    payload: SellRequest,
    _auth: str = Depends(admin_api_guard),
    session: Session = Depends(get_session),
) -> dict:
    try:
        result = create_sell(session, payload)
        backup_path = _commit_with_backup(session)
        return {"ok": True, **result, "backup": backup_path}
    except HTTPException:
        session.rollback()
        raise
    except Exception as exc:  # pragma: no cover
        session.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/lot/sl")
def api_lot_sl(
    payload: LotSLUpdateRequest,
    _auth: str = Depends(admin_api_guard),
    session: Session = Depends(get_session),
) -> dict:
    try:
        result = update_lot_sl(session, payload)
        backup_path = _commit_with_backup(session)
        return {"ok": True, **result, "backup": backup_path}
    except HTTPException:
        session.rollback()
        raise
    except Exception as exc:  # pragma: no cover
        session.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/cashflow")
def api_cashflow(
    payload: CashflowRequest,
    _auth: str = Depends(admin_api_guard),
    session: Session = Depends(get_session),
) -> dict:
    try:
        result = create_cashflow(session, payload)
        backup_path = _commit_with_backup(session)
        return {"ok": True, **result, "backup": backup_path}
    except HTTPException:
        session.rollback()
        raise
    except Exception as exc:  # pragma: no cover
        session.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/review")
def api_review(
    payload: ReviewRequest,
    _auth: str = Depends(admin_api_guard),
    session: Session = Depends(get_session),
) -> dict:
    try:
        result = create_review(session, payload)
        backup_path = _commit_with_backup(session)
        return {"ok": True, **result, "backup": backup_path}
    except HTTPException:
        session.rollback()
        raise
    except Exception as exc:  # pragma: no cover
        session.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/events/duplicate-check")
def api_event_duplicate_check(
    payload: DuplicateCheckRequest,
    _auth: str = Depends(admin_api_guard),
    session: Session = Depends(get_session),
) -> dict:
    return check_duplicate_event(session, payload)


@app.patch("/api/events/{event_id}")
def api_event_update(
    event_id: int,
    payload: EventUpdateRequest,
    _auth: str = Depends(admin_api_guard),
    session: Session = Depends(get_session),
) -> dict:
    try:
        result = update_event(session, event_id, payload)
        backup_path = _commit_with_backup(session)
        return {"ok": True, **result, "backup": backup_path}
    except HTTPException:
        session.rollback()
        raise
    except Exception as exc:  # pragma: no cover
        session.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.delete("/api/events/{event_id}")
def api_event_delete(
    event_id: int,
    _auth: str = Depends(admin_api_guard),
    session: Session = Depends(get_session),
) -> dict:
    try:
        result = delete_event(session, event_id)
        backup_path = _commit_with_backup(session)
        return {"ok": True, **result, "backup": backup_path}
    except HTTPException:
        session.rollback()
        raise
    except Exception as exc:  # pragma: no cover
        session.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/market-data/status")
def api_market_data_status(
    _auth: str = Depends(viewer_api_guard),
) -> dict:
    return get_market_data_cache_status()


@app.post("/api/market-data/refresh")
def api_market_data_refresh(
    clear_name_cache: bool = Query(default=False),
    _auth: str = Depends(admin_api_guard),
) -> dict:
    return refresh_market_data_cache(clear_name_cache=clear_name_cache)


@app.get("/api/portfolio")
def api_portfolio(
    _auth: str = Depends(viewer_api_guard),
    session: Session = Depends(get_session),
) -> dict:
    return build_portfolio(session)


@app.get("/api/journal")
def api_journal(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    q: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    hf_ticker: list[str] = Query(default=[]),
    hf_market: list[str] = Query(default=[]),
    hf_currency: list[str] = Query(default=[]),
    hf_symbol_name: list[str] = Query(default=[]),
    hf_type: list[str] = Query(default=[]),
    hf_win_lose: list[str] = Query(default=[]),
    _auth: str = Depends(viewer_api_guard),
    session: Session = Depends(get_session),
) -> dict:
    return build_journal(
        session,
        page=page,
        page_size=page_size,
        query=q,
        event_type=event_type,
        date_from=date_from,
        date_to=date_to,
        hf_ticker=hf_ticker,
        hf_market=hf_market,
        hf_currency=hf_currency,
        hf_symbol_name=hf_symbol_name,
        hf_type=hf_type,
        hf_win_lose=hf_win_lose,
    )


@app.get("/api/stats")
def api_stats(
    _auth: str = Depends(viewer_api_guard),
    session: Session = Depends(get_session),
) -> dict:
    return build_stats(session)


@app.get("/api/benchmark/returns")
def api_benchmark_returns(
    symbol: str = Query(default="SPY"),
    _auth: str = Depends(viewer_api_guard),
    session: Session = Depends(get_session),
) -> dict:
    return build_benchmark_returns(session, symbol)


@app.get("/api/fx/history")
def api_fx_history(
    currency: str = Query(...),
    days: int = Query(default=90, ge=7, le=365),
    quote_currency: str | None = Query(default=None),
    _auth: str = Depends(viewer_api_guard),
    session: Session = Depends(get_session),
) -> dict:
    return build_fx_history(session, currency, days, quote_currency=quote_currency)


@app.post("/api/upload-image")
async def api_upload_image(
    file: UploadFile = File(...),
    _auth: str = Depends(admin_api_guard),
) -> dict:
    content = await file.read()
    image_url = save_uploaded_image(content=content, content_type=file.content_type)
    return {"ok": True, "image_url": image_url}


@app.get("/journal", response_class=HTMLResponse)
def page_journal(
    request: Request,
    page: int = Query(default=1, ge=1),
    q: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    hf_ticker: list[str] = Query(default=[]),
    hf_market: list[str] = Query(default=[]),
    hf_currency: list[str] = Query(default=[]),
    hf_symbol_name: list[str] = Query(default=[]),
    hf_type: list[str] = Query(default=[]),
    hf_win_lose: list[str] = Query(default=[]),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    role = _require_viewer_page_role(request)
    if role is None:
        return RedirectResponse(url="/access", status_code=303)

    data = build_journal(
        session,
        page=page,
        page_size=50,
        query=q,
        event_type=event_type,
        date_from=date_from,
        date_to=date_to,
        hf_ticker=hf_ticker,
        hf_market=hf_market,
        hf_currency=hf_currency,
        hf_symbol_name=hf_symbol_name,
        hf_type=hf_type,
        hf_win_lose=hf_win_lose,
    )
    data["page_urls"] = [
        {
            "page": p,
            "url": _journal_page_url(
                p,
                q,
                event_type,
                date_from,
                date_to,
                hf_ticker=hf_ticker,
                hf_market=hf_market,
                hf_currency=hf_currency,
                hf_symbol_name=hf_symbol_name,
                hf_type=hf_type,
                hf_win_lose=hf_win_lose,
            ),
        }
        for p in data["page_numbers"]
    ]
    data["prev_url"] = (
        _journal_page_url(
            data["prev_page"],
            q,
            event_type,
            date_from,
            date_to,
            hf_ticker=hf_ticker,
            hf_market=hf_market,
            hf_currency=hf_currency,
            hf_symbol_name=hf_symbol_name,
            hf_type=hf_type,
            hf_win_lose=hf_win_lose,
        )
        if data["has_prev"] and data["prev_page"] is not None
        else None
    )
    data["next_url"] = (
        _journal_page_url(
            data["next_page"],
            q,
            event_type,
            date_from,
            date_to,
            hf_ticker=hf_ticker,
            hf_market=hf_market,
            hf_currency=hf_currency,
            hf_symbol_name=hf_symbol_name,
            hf_type=hf_type,
            hf_win_lose=hf_win_lose,
        )
        if data["has_next"] and data["next_page"] is not None
        else None
    )
    portfolio = build_portfolio(session)
    return templates.TemplateResponse(
        "journal.html",
        {
            "request": request,
            "data": data,
            "portfolio": portfolio,
            **_template_auth_context(request),
        },
    )


@app.get("/portfolio", response_class=HTMLResponse)
def page_portfolio(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    role = _require_viewer_page_role(request)
    if role is None:
        return RedirectResponse(url="/access", status_code=303)

    data = build_portfolio(session)
    return templates.TemplateResponse(
        "portfolio.html",
        {
            "request": request,
            "data": data,
            **_template_auth_context(request),
        },
    )


@app.get("/stats", response_class=HTMLResponse)
def page_stats(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    role = _require_viewer_page_role(request)
    if role is None:
        return RedirectResponse(url="/access", status_code=303)

    data = build_stats(session)
    benchmark_prefetch: dict[str, dict] = {}
    for symbol in data.get("benchmark_symbols", []):
        try:
            benchmark_prefetch[symbol] = build_benchmark_returns(session, symbol, stats=data)
        except HTTPException as exc:
            benchmark_prefetch[symbol] = {
                "symbol": symbol,
                "source_symbol": symbol,
                "daily": [],
                "weekly": [],
                "monthly": [],
                "yearly": [],
                "error": str(exc.detail),
            }
        except Exception as exc:
            benchmark_prefetch[symbol] = {
                "symbol": symbol,
                "source_symbol": symbol,
                "daily": [],
                "weekly": [],
                "monthly": [],
                "yearly": [],
                "error": str(exc),
            }

    return templates.TemplateResponse(
        "stats.html",
        {
            "request": request,
            "data": data,
            "benchmark_prefetch": benchmark_prefetch,
            **_template_auth_context(request),
        },
    )


@app.get("/trades/{trade_group_id}", response_class=HTMLResponse)
def page_trade_detail(
    trade_group_id: int,
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    role = _require_viewer_page_role(request)
    if role is None:
        return RedirectResponse(url="/access", status_code=303)

    data = build_trade_detail(session, trade_group_id)
    return templates.TemplateResponse(
        "trade_detail.html",
        {
            "request": request,
            "data": data,
            **_template_auth_context(request),
        },
    )


@app.get("/export/events.csv")
def export_events(
    _auth: str = Depends(admin_api_guard),
    session: Session = Depends(get_session),
) -> Response:
    content = export_events_csv(session)
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=events.csv"},
    )


@app.get("/export/lots.csv")
def export_lots(
    _auth: str = Depends(admin_api_guard),
    session: Session = Depends(get_session),
) -> Response:
    content = export_lots_csv(session)
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=lots.csv"},
    )


@app.get("/export/sell_allocations.csv")
def export_sell_allocations(
    _auth: str = Depends(admin_api_guard),
    session: Session = Depends(get_session),
) -> Response:
    content = export_sell_allocations_csv(session)
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sell_allocations.csv"},
    )
