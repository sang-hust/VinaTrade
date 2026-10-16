"""Idempotent seed: admin account, strategies, preset screeners, data sources, default config rows.
Run: python -m app.seeds.seed  (start.sh runs it on every deploy)."""

import asyncio
import logging

from sqlalchemy import select

from app.core.config import settings
from app.core.db import session_scope
from app.core.security import hash_password
from app.engines.strategies import STRATEGIES
from app.models import DataSource, Screener, Strategy, User, UserSettings
from app.screener.presets import PRESETS, build_dsl
from app.services.riskguard import ensure_user_defaults
from app.services.sysconfig import DEFAULTS, get_config, set_config

log = logging.getLogger(__name__)


async def seed() -> dict:
    out = {}
    async with session_scope() as db:
        # admin
        admin = (await db.execute(select(User).where(User.email == settings.admin_email.lower()))).scalar_one_or_none()
        if admin is None:
            admin = User(email=settings.admin_email.lower(), full_name=settings.admin_name, password_hash=hash_password(settings.admin_password), role="ADMIN", status="ACTIVE")
            db.add(admin)
            await db.flush()
            db.add(UserSettings(user_id=admin.id, ui_detail="FULL"))
            out["admin"] = "created"
        else:
            admin.role, admin.status = "ADMIN", "ACTIVE"
            out["admin"] = "exists"
        admin.max_devices = max(admin.max_devices or 0, 10)
        st = await db.get(UserSettings, admin.id)
        if st and st.onboarded_at is None:
            from datetime import UTC, datetime
            st.onboarded_at = datetime.now(UTC)  # admin lands on Thị trường; settings editable in Tài khoản
        await ensure_user_defaults(db, admin, await get_config(db, "risk.defaults"))
        # strategies
        n = 0
        for code, name, stype, hz, desc in STRATEGIES:
            st = await db.get(Strategy, code)
            if st is None:
                db.add(Strategy(code=code, name=name, signal_type=stype, horizon=hz, description=desc, enabled=True, backtest_years=6.0))
                n += 1
            else:
                st.name, st.signal_type, st.horizon, st.description = name, stype, hz, desc
        out["strategies_new"] = n
        # presets
        n = 0
        for p in PRESETS:
            row = (await db.execute(select(Screener).where(Screener.code == p["code"]))).scalar_one_or_none()
            dsl = build_dsl(p["core"], p["form"], p["horizon"])
            if row is None:
                db.add(Screener(code=p["code"], name=p["name"], description=p["description"], group=p["group"], horizon=p["horizon"], conditions={"all": p["core"]} if p["core"] else {"all": []},
                                form_state=p["form"], is_preset=True, position=PRESETS.index(p)))
                n += 1
            else:
                row.name, row.description, row.group, row.horizon = p["name"], p["description"], p["group"], p["horizon"]
                if row.form_state is None:  # admin never customised → refresh from code
                    row.conditions, row.form_state = {"all": p["core"]}, p["form"]
            _ = dsl
        out["presets_new"] = n
        # data sources
        for code, name, role, prio in (("SSI", "SSI iBoard", "PRIMARY", 1), ("VCI", "Vietcap", "BACKUP", 2), ("FILE", "Nhập file giá", "BACKUP", 9)):
            if await db.get(DataSource, code) is None:
                db.add(DataSource(code=code, name=name, role=role, priority=prio))
        # config rows (materialise defaults so admin sees them)
        for key, (val, _d, _g) in DEFAULTS.items():
            if await get_config(db, key) is None:
                await set_config(db, key, val, None)
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(asyncio.run(seed()))
