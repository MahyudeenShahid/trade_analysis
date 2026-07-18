"""IBKR REST API routes master hub."""

from fastapi import APIRouter
from .ibkr_connection import router as connection_router
from .ibkr_orders import router as orders_router
from .ibkr_book import router as book_router
from .ibkr_replay import router as replay_router
from .ibkr_rule14 import router as rule14_router
from .ibkr_rule12 import router as rule12_router

router = APIRouter(prefix="/ibkr", tags=["ibkr"])

# Include the modular sub-routers
router.include_router(connection_router)
router.include_router(orders_router)
router.include_router(book_router)
router.include_router(replay_router)
router.include_router(rule14_router)
router.include_router(rule12_router)

# Re-export _auto_save_trade_replay for compatibility with order routing calls
from .ibkr_replay import _auto_save_trade_replay
