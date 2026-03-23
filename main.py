"""
Pokemon TCG Restock Monitor
===========================
Monitors: Pokemon Center, Amazon, Walmart, Target, Best Buy, GameStop
Alerts via: Discord Webhook, Email (SMTP), SMS (Twilio)
Dashboard: open dashboard.html in your browser while this script is running

SETUP:
  py -3.12 -m pip install -r requirements.txt
  py -3.12 -m playwright install chromium
  py -3.12 main.py

Then open dashboard.html in your browser — it will show live real data.
"""

import os
import json
import time
import logging
import smtplib
import hashlib
import schedule
import requests
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

# ─────────────────────────────────────────────
# AUTO-INSTALL PLAYWRIGHT BROWSERS ON STARTUP
# Runs once when the script starts — ensures
# Chromium is available even on fresh deploys
# ─────────────────────────────────────────────
import subprocess
import sys

def ensure_playwright_browsers():
    try:
        # Install system dependencies first
        subprocess.run(
            [sys.executable, "-m", "playwright", "install-deps", "chromium"],
            capture_output=True, text=True, timeout=300
        )
        # Then install the browser binary
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True, text=True, timeout=300
        )
        if result.returncode == 0:
            print("✓ Playwright Chromium ready")
        else:
            print(f"⚠ Playwright install warning: {result.stderr[:200]}")
    except Exception as e:
        print(f"⚠ Could not auto-install Playwright browsers: {e}")

ensure_playwright_browsers()

# ─────────────────────────────────────────────
# CONFIG — set these in your .env file
# ─────────────────────────────────────────────
DISCORD_WEBHOOK_URL  = os.getenv("DISCORD_WEBHOOK_URL", "")
EMAIL_FROM           = os.getenv("EMAIL_FROM", "")
EMAIL_TO             = os.getenv("EMAIL_TO", "")
EMAIL_PASSWORD       = os.getenv("EMAIL_PASSWORD", "")
TWILIO_ACCOUNT_SID   = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN    = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER   = os.getenv("TWILIO_FROM_NUMBER", "")
TWILIO_TO_NUMBER     = os.getenv("TWILIO_TO_NUMBER", "")
CHECK_INTERVAL_MINS  = int(os.getenv("CHECK_INTERVAL_MINS", "5"))
MAX_PRICE_THRESHOLD  = float(os.getenv("MAX_PRICE_THRESHOLD", "0"))
DASHBOARD_PORT       = int(os.getenv("DASHBOARD_PORT", "8765"))

ALERT_COOLDOWN_SECS  = 3600

# ─────────────────────────────────────────────
# WATCHLIST
# ─────────────────────────────────────────────
WATCHLIST = [
    # ════════════════════════════════════════════════════════════════
    # MEGA EVOLUTION — ASCENDED HEROES
    # ════════════════════════════════════════════════════════════════
    # ETB
    { "store": "Pokemon Center", "name": "Ascended Heroes PC ETB",
      "url": "https://www.pokemoncenter.com/product/10-10315-101/pokemon-tcg-mega-evolution-ascended-heroes-pokemon-center-elite-trainer-box",
      "max_price": 63.99 },
    { "store": "Amazon", "name": "Ascended Heroes ETB",
      "url": "https://www.amazon.com/dp/B0G3CY83L5", "max_price": 54.99 },
    { "store": "Walmart", "name": "Ascended Heroes ETB",
      "url": "https://www.walmart.com/ip/18710966734", "max_price": 49.99 },
    { "store": "Target", "name": "Ascended Heroes ETB",
      "url": "https://www.target.com/p/-/A-1010148053", "max_price": 49.99 },
    { "store": "Best Buy", "name": "Ascended Heroes ETB",
      "url": "https://www.bestbuy.com/product/JJG2TLXSFV", "max_price": 49.99 },
    { "store": "GameStop", "name": "Ascended Heroes ETB",
      "url": "https://www.gamestop.com/toys-games/trading-cards/products/pokemon-trading-card-game-ascended-heroes-elite-trainer-box/20030564.html",
      "max_price": 49.99 },
    # Booster Bundle
    { "store": "Pokemon Center", "name": "Ascended Heroes Booster Bundle",
      "url": "https://www.pokemoncenter.com/product/10-10311-114/pokemon-tcg-mega-evolution-ascended-heroes-booster-bundle-6-packs",
      "max_price": 29.99 },
    { "store": "Amazon", "name": "Ascended Heroes Booster Bundle",
      "url": "https://www.amazon.com/dp/B0G3CV6Z9D", "max_price": 29.99 },
    { "store": "Walmart", "name": "Ascended Heroes Booster Bundle",
      "url": "https://www.walmart.com/ip/18728422476", "max_price": 29.99 },
    { "store": "Best Buy", "name": "Ascended Heroes Booster Bundle",
      "url": "https://www.bestbuy.com/product/JJG2TL3JP8", "max_price": 29.99 },
    { "store": "GameStop", "name": "Ascended Heroes Booster Bundle",
      "url": "https://www.gamestop.com/toys-games/trading-cards/products/pokemon-trading-card-game-ascended-heroes-booster-bundle/20030569.html",
      "max_price": 29.99 },
    # Booster Box
    { "store": "GameStop", "name": "Ascended Heroes Booster Box (36 packs)",
      "url": "https://www.gamestop.com/toys-games/trading-cards/products/pokemon-trading-card-game-ascended-heroes-booster-box/438940.html",
      "max_price": 149.99 },

    # ════════════════════════════════════════════════════════════════
    # MEGA EVOLUTION — PERFECT ORDER
    # ════════════════════════════════════════════════════════════════
    # ETB
    { "store": "Pokemon Center", "name": "Perfect Order PC ETB",
      "url": "https://www.pokemoncenter.com/product/10-10372-109/pokemon-tcg-mega-evolution-perfect-order-pokemon-center-elite-trainer-box",
      "max_price": 63.99 },
    { "store": "Walmart", "name": "Perfect Order ETB",
      "url": "https://www.walmart.com/ip/Pokemon-TCG-Mega-Evolution-Perfect-Order-Elite-Trainer-Box/19402160990",
      "max_price": 49.99 },
    { "store": "Target", "name": "Perfect Order ETB",
      "url": "https://www.target.com/p/-/A-95230445", "max_price": 49.99 },
    { "store": "Best Buy", "name": "Perfect Order ETB",
      "url": "https://www.bestbuy.com/product/pokemon-trading-card-game-mega-evolution-perfect-order-elite-trainer-box/JJG2TL3W86",
      "max_price": 49.99 },
    { "store": "GameStop", "name": "Perfect Order ETB",
      "url": "https://www.gamestop.com/toys-games/trading-cards/products/pokemon-trading-card-game-perfect-order-elite-trainer-box/20031957.html",
      "max_price": 49.99 },
    # Booster Bundle
    { "store": "Pokemon Center", "name": "Perfect Order Booster Bundle",
      "url": "https://www.pokemoncenter.com/product/10-10377-109", "max_price": 29.99 },
    { "store": "GameStop", "name": "Perfect Order Booster Bundle",
      "url": "https://www.gamestop.com/toys-games/trading-cards/products/pokemon-trading-card-game-perfect-order-booster-bundle-box/20031960.html",
      "max_price": 29.99 },
    # Booster Box
    { "store": "GameStop", "name": "Perfect Order Booster Box (36 packs)",
      "url": "https://www.gamestop.com/toys-games/trading-cards/products/pokemon-trading-card-game-perfect-order-booster-box/438940.html",
      "max_price": 149.99 },

    # ════════════════════════════════════════════════════════════════
    # SCARLET & VIOLET — DESTINED RIVALS
    # ════════════════════════════════════════════════════════════════
    # ETB
    { "store": "Pokemon Center", "name": "Destined Rivals ETB",
      "url": "https://www.pokemoncenter.com/category/destined-rivals", "max_price": 59.99 },
    { "store": "Walmart", "name": "Destined Rivals ETB",
      "url": "https://www.walmart.com/ip/15718673510", "max_price": 49.99 },
    { "store": "Target", "name": "Destined Rivals ETB",
      "url": "https://www.target.com/p/-/A-94300069", "max_price": 49.99 },
    { "store": "Best Buy", "name": "Destined Rivals ETB",
      "url": "https://www.bestbuy.com/site/pokemon-trading-card-game-scarlet-violet-destined-rivals-elite-trainer-box/6624825.p",
      "max_price": 49.99 },
    { "store": "GameStop", "name": "Destined Rivals ETB",
      "url": "https://www.gamestop.com/toys-games/trading-cards/products/pokemon-trading-card-game-destined-rivals-elite-trainer-box/20021586.html",
      "max_price": 49.99 },
    # Booster Bundle
    { "store": "Pokemon Center", "name": "Destined Rivals Booster Bundle",
      "url": "https://www.pokemoncenter.com/product/100-10638/pokemon-tcg-scarlet-and-violet-destined-rivals-booster-bundle-6-packs",
      "max_price": 26.99 },
    { "store": "Walmart", "name": "Destined Rivals Booster Bundle",
      "url": "https://www.walmart.com/ip/Pokemon-TCG-Scarlet-Violet-Destined-Rivals-Booster-Bundle/16749906607",
      "max_price": 26.99 },
    { "store": "Target", "name": "Destined Rivals Booster Bundle",
      "url": "https://www.target.com/p/-/A-94300067", "max_price": 26.99 },
    { "store": "Best Buy", "name": "Destined Rivals Booster Bundle",
      "url": "https://www.bestbuy.com/product/pokemon-trading-card-game-scarlet-violet-destined-rivals-6pk-booster-bundle/JJG2TL2239",
      "max_price": 26.99 },
    { "store": "GameStop", "name": "Destined Rivals Booster Bundle",
      "url": "https://www.gamestop.com/toys-games/trading-cards/products/pokemon-trading-card-game-destined-rivals-booster-bundle/20021585.html",
      "max_price": 26.99 },
    # Booster Box
    { "store": "Pokemon Center", "name": "Destined Rivals Booster Box (36 packs)",
      "url": "https://www.pokemoncenter.com/product/10-10157-101/pokemon-tcg-scarlet-and-violet-destined-rivals-booster-display-box-36-packs",
      "max_price": 161.99 },
    { "store": "Best Buy", "name": "Destined Rivals Booster Box (36 packs)",
      "url": "https://www.bestbuy.com/product/pokemon-trading-card-game-scarlet-violet-destined-rivals-booster-box-36-packs/JJG2TL25CG",
      "max_price": 149.99 },
    { "store": "GameStop", "name": "Destined Rivals Booster Box (36 packs)",
      "url": "https://www.gamestop.com/toys-games/trading-cards/products/pokemon-trading-card-game-destined-rivals-booster-box/20021587.html",
      "max_price": 149.99 },

    # ════════════════════════════════════════════════════════════════
    # SCARLET & VIOLET — JOURNEY TOGETHER
    # ════════════════════════════════════════════════════════════════
    # ETB
    { "store": "Pokemon Center", "name": "Journey Together PC ETB",
      "url": "https://www.pokemoncenter.com/category/journey-together", "max_price": 59.99 },
    { "store": "Walmart", "name": "Journey Together ETB",
      "url": "https://www.walmart.com/ip/Pokemon-TCG-SV09-Journey-Together-Elite-Trainer-Box-ETB/15749501336",
      "max_price": 49.99 },
    { "store": "Target", "name": "Journey Together ETB",
      "url": "https://www.target.com/p/-/A-93803439", "max_price": 49.99 },
    { "store": "Best Buy", "name": "Journey Together ETB",
      "url": "https://www.bestbuy.com/product/JJG2TLCFTX", "max_price": 49.99 },
    { "store": "GameStop", "name": "Journey Together ETB",
      "url": "https://www.gamestop.com/toys-games/trading-cards/products/pokemon-trading-card-game-scarlet-and-violet-journey-together-elite-trainer-box/20019414.html",
      "max_price": 49.99 },
    # Booster Bundle
    { "store": "Pokemon Center", "name": "Journey Together Booster Bundle",
      "url": "https://www.pokemoncenter.com/product/100-10341/pokemon-tcg-scarlet-and-violet-journey-together-booster-bundle-6-packs",
      "max_price": 26.99 },
    { "store": "Walmart", "name": "Journey Together Booster Bundle",
      "url": "https://www.walmart.com/ip/Pokemon-TCG-SV09-Journey-Together-Booster-Bundle-6-Packs/15780068131",
      "max_price": 26.99 },
    { "store": "Target", "name": "Journey Together Booster Bundle",
      "url": "https://www.target.com/p/-/A-94300074", "max_price": 26.99 },
    { "store": "Best Buy", "name": "Journey Together Booster Bundle",
      "url": "https://www.bestbuy.com/site/pokemon-trading-card-game-scarlet-violet-journey-together-booster-bundle-6-pk/6614264.p",
      "max_price": 26.99 },
    { "store": "GameStop", "name": "Journey Together Booster Bundle",
      "url": "https://www.gamestop.com/toys-games/trading-cards/products/pokemon-trading-card-game-scarlet-and-violet-journey-together-booster-bundle/20019415.html",
      "max_price": 26.99 },
    # Booster Box
    { "store": "Pokemon Center", "name": "Journey Together Booster Box (36 packs)",
      "url": "https://www.pokemoncenter.com/product/10-10125-102/pokemon-tcg-scarlet-and-violet-journey-together-enhanced-booster-display-box-36-packs-and-1-promo-card",
      "max_price": 161.99 },
    { "store": "Best Buy", "name": "Journey Together Booster Box (36 packs)",
      "url": "https://www.bestbuy.com/product/pokemon-trading-card-game-scarlet-violet-journey-together-booster-box-36-packs/JJG2TL2QS8",
      "max_price": 149.99 },

    # ════════════════════════════════════════════════════════════════
    # SCARLET & VIOLET — PRISMATIC EVOLUTIONS
    # ════════════════════════════════════════════════════════════════
    # ETB
    { "store": "Pokemon Center", "name": "Prismatic Evolutions PC ETB",
      "url": "https://www.pokemoncenter.com/product/100-10019/pokemon-tcg-scarlet-and-violet-prismatic-evolutions-pokemon-center-elite-trainer-box",
      "max_price": 63.99 },
    { "store": "Amazon", "name": "Prismatic Evolutions ETB",
      "url": "https://www.amazon.com/dp/B0DLPL7LC5", "max_price": 54.99 },
    { "store": "Walmart", "name": "Prismatic Evolutions ETB",
      "url": "https://www.walmart.com/ip/15160152062", "max_price": 49.99 },
    { "store": "Target", "name": "Prismatic Evolutions ETB",
      "url": "https://www.target.com/p/-/A-93954435", "max_price": 49.99 },
    { "store": "Best Buy", "name": "Prismatic Evolutions ETB",
      "url": "https://www.bestbuy.com/product/JJG2TLCW3L", "max_price": 49.99 },
    { "store": "GameStop", "name": "Prismatic Evolutions ETB",
      "url": "https://www.gamestop.com/toys-games/trading-cards/products/pokemon-trading-card-game-prismatic-evolutions-elite-trainer-box/20018505.html",
      "max_price": 49.99 },
    # Booster Bundle
    { "store": "Pokemon Center", "name": "Prismatic Evolutions Booster Bundle",
      "url": "https://www.pokemoncenter.com/product/10-10025-101/pokemon-tcg-scarlet-and-violet-prismatic-evolutions-booster-bundle-6-packs",
      "max_price": 26.99 },
    { "store": "Amazon", "name": "Prismatic Evolutions Booster Bundle",
      "url": "https://www.amazon.com/dp/B0DN98RVZM", "max_price": 29.99 },
    { "store": "Walmart", "name": "Prismatic Evolutions Booster Bundle",
      "url": "https://www.walmart.com/ip/POKEMON-SV8-5-PRISMATIC-EVO-BST-BUNDLE/14803962651",
      "max_price": 26.99 },
    { "store": "Target", "name": "Prismatic Evolutions Booster Bundle",
      "url": "https://www.target.com/p/-/A-93954446", "max_price": 26.99 },
    { "store": "Best Buy", "name": "Prismatic Evolutions Booster Bundle",
      "url": "https://www.bestbuy.com/product/pokemon-trading-card-game-scarlet-violet-prismatic-evolutions-booster-bundle/JJG2TL23JK",
      "max_price": 26.99 },
    { "store": "GameStop", "name": "Prismatic Evolutions Booster Bundle",
      "url": "https://www.gamestop.com/toys-games/trading-cards/products/pokemon-trading-card-game-prismatic-evolutions-booster-bundle/20018824.html",
      "max_price": 26.99 },
    # Individual Pack
    { "store": "Amazon", "name": "Prismatic Evolutions Booster Pack (single)",
      "url": "https://www.amazon.com/dp/B0DWGV8R2N", "max_price": 5.99 },

    # ════════════════════════════════════════════════════════════════
    # SCARLET & VIOLET — SURGING SPARKS
    # ════════════════════════════════════════════════════════════════
    # ETB
    { "store": "Best Buy", "name": "Surging Sparks ETB",
      "url": "https://www.bestbuy.com/product/pokemon-trading-card-game-scarlet-violet-surging-sparks-elite-trainer-box/J3YSYH8G3V",
      "max_price": 49.99 },
    # Booster Bundle
    { "store": "Best Buy", "name": "Surging Sparks Booster Bundle",
      "url": "https://www.bestbuy.com/product/pokemon-trading-card-game-scarlet-violet-surging-sparks-6-pk-booster-bundle/J3YSYH8G46",
      "max_price": 26.99 },
    # 3-Pack Blister
    { "store": "Best Buy", "name": "Surging Sparks 3-Pack Blister",
      "url": "https://www.bestbuy.com/product/pokemon-trading-card-game-scarlet-violet-surging-sparks-3pk-booster-styles-may-vary/J3YSYH8G76",
      "max_price": 13.99 },

    # ════════════════════════════════════════════════════════════════
    # SCARLET & VIOLET — STELLAR CROWN
    # ════════════════════════════════════════════════════════════════
    # ETB
    { "store": "GameStop", "name": "Stellar Crown ETB",
      "url": "https://www.gamestop.com/toys-games/trading-cards/products/pokemon-trading-card-game-scarlet-and-violet-stellar-crown-elite-trainer-box/20013905.html",
      "max_price": 49.99 },
    # Booster Bundle
    { "store": "GameStop", "name": "Stellar Crown Booster Bundle",
      "url": "https://www.gamestop.com/toys-games/trading-cards/products/pokemon-trading-card-game-scarlet-and-violet-stellar-crown-booster-bundle/20013922.html",
      "max_price": 26.99 },

    # ════════════════════════════════════════════════════════════════
    # SCARLET & VIOLET — TWILIGHT MASQUERADE
    # ════════════════════════════════════════════════════════════════
    # ETB
    { "store": "Walmart", "name": "Twilight Masquerade ETB",
      "url": "https://www.walmart.com/ip/Pokemon-Trading-Card-Games-SV6-Twilight-Masquerade-Elite-Trainer-Box/5558569421",
      "max_price": 49.99 },
    { "store": "GameStop", "name": "Twilight Masquerade ETB",
      "url": "https://www.gamestop.com/toys-games/trading-cards/products/pokemon-trading-card-game-twilight-masquerade-elite-trainer-box/20011215.html",
      "max_price": 49.99 },
    # Booster Box
    { "store": "Best Buy", "name": "Twilight Masquerade Booster Box (36 packs)",
      "url": "https://www.bestbuy.com/site/pokemon-trading-card-game-twilight-masquerade-booster-box-36-packs/6578901.p",
      "max_price": 149.99 },
    { "store": "Walmart", "name": "Twilight Masquerade Booster Box (36 packs)",
      "url": "https://www.walmart.com/ip/Pokemon-TCG-Twilight-Masquerade-Booster-Box-36-Packs/5736034613",
      "max_price": 149.99 },

    # ════════════════════════════════════════════════════════════════
    # SCARLET & VIOLET — TEMPORAL FORCES
    # ════════════════════════════════════════════════════════════════
    # 3-Pack Blister
    { "store": "Best Buy", "name": "Temporal Forces 3-Pack Blister",
      "url": "https://www.bestbuy.com/product/pokemon-trading-card-game-scarlet-violet-temporal-forces-3pk-booster-styles-may-vary/J3YSYH8CL9",
      "max_price": 13.99 },

    # ════════════════════════════════════════════════════════════════
    # SCARLET & VIOLET — PALDEAN FATES
    # ════════════════════════════════════════════════════════════════
    # ETB
    { "store": "Pokemon Center", "name": "Paldean Fates ETB",
      "url": "https://www.pokemoncenter.com/category/paldean-fates", "max_price": 49.99 },
    { "store": "Walmart", "name": "Paldean Fates ETB",
      "url": "https://www.walmart.com/ip/POKEMON-SV4-5-PALDEAN-FATES-ETB/5226743070",
      "max_price": 49.99 },
    { "store": "Target", "name": "Paldean Fates ETB",
      "url": "https://www.target.com/p/-/A-89432659", "max_price": 49.99 },
    { "store": "Best Buy", "name": "Paldean Fates ETB",
      "url": "https://www.bestbuy.com/site/pokemon-trading-card-game-scarlet-violet-paldean-fates-elite-trainer-box/6568010.p",
      "max_price": 49.99 },
    { "store": "GameStop", "name": "Paldean Fates ETB",
      "url": "https://www.gamestop.com/toys-games/trading-cards/products/pokemon-trading-card-game-paldean-fates-booster-bundle/20009334.html",
      "max_price": 49.99 },
    # Booster Bundle
    { "store": "Pokemon Center", "name": "Paldean Fates Booster Bundle",
      "url": "https://www.pokemoncenter.com/product/699-85739/pokemon-tcg-scarlet-and-violet-paldean-fates-booster-bundle",
      "max_price": 26.99 },
    { "store": "Walmart", "name": "Paldean Fates Booster Bundle",
      "url": "https://www.walmart.com/ip/Pokemon-Trading-Card-Games-SV4-5-Paldean-Fates-Booster-Bundle/5226743077",
      "max_price": 26.99 },
    { "store": "Target", "name": "Paldean Fates Booster Bundle",
      "url": "https://www.target.com/p/-/A-89432660", "max_price": 26.99 },
    { "store": "Best Buy", "name": "Paldean Fates Booster Bundle",
      "url": "https://www.bestbuy.com/product/pokemon-trading-card-game-scarlet-violet-paldean-fates-6pk-booster-bundle/J3YSYH8J45",
      "max_price": 26.99 },
    { "store": "GameStop", "name": "Paldean Fates Booster Bundle (alt)",
      "url": "https://www.gamestop.com/toys-games/trading-cards/products/pokemon-trading-card-game-paldean-fates-booster-bundle/402363.html",
      "max_price": 26.99 },

    # ════════════════════════════════════════════════════════════════
    # SCARLET & VIOLET — PARADOX RIFT
    # ════════════════════════════════════════════════════════════════
    # ETB
    { "store": "Target", "name": "Paradox Rift ETB",
      "url": "https://www.target.com/p/-/A-88602567", "max_price": 49.99 },
    # Booster Box
    { "store": "Walmart", "name": "Paradox Rift Booster Box (36 packs)",
      "url": "https://www.walmart.com/ip/Pokemon-TCG-Paradox-Rift-Booster-Display-Box-36-Packs/5045168168",
      "max_price": 149.99 },
]

# ─────────────────────────────────────────────
# STORE SCRAPING CONFIGS
# ─────────────────────────────────────────────
STORE_CONFIGS = {
    "Pokemon Center": {
        "out_of_stock_selectors": [
            "[class*='out-of-stock']",
            "button[disabled][class*='add-to-cart']",
            "[data-testid='sold-out']",
        ],
        "add_to_cart_selector": "button[class*='add-to-cart']:not([disabled])",
        "price_selector": "[class*='price']",
        "use_playwright": True,
    },
    "Amazon": {
        "out_of_stock_selectors": ["#availability .a-color-state", "#outOfStock"],
        "add_to_cart_selector": "#add-to-cart-button:not([disabled])",
        "price_selector": ".a-price .a-offscreen, #priceblock_ourprice, .a-price-whole",
        "use_playwright": True,
    },
    "Walmart": {
        "out_of_stock_selectors": ["[aria-label='Out of stock']", "[class*='unavailable']"],
        "add_to_cart_selector": "button[data-automation-id='add-to-cart']:not([disabled])",
        "price_selector": "[itemprop='price'], [class*='price-main']",
        "use_playwright": True,
    },
    "Target": {
        "out_of_stock_selectors": ["[data-test='outOfStockButton']", "[class*='styles__SoldOut']"],
        "add_to_cart_selector": "[data-test='shippingATCButton']:not([disabled])",
        "price_selector": "[data-test='product-price']",
        "use_playwright": True,
    },
    "Best Buy": {
        "out_of_stock_selectors": [".btn-disabled.add-to-cart-button", "[class*='soldOut']"],
        "add_to_cart_selector": ".add-to-cart-button:not(.btn-disabled)",
        "price_selector": ".priceView-customer-price span",
        "use_playwright": True,
    },
    "GameStop": {
        "out_of_stock_selectors": [".notifyme-button", "[class*='out-of-stock']"],
        "add_to_cart_selector": ".add-to-cart:not(.disabled)",
        "price_selector": ".actual-price",
        "use_playwright": True,
    },
}

# ─────────────────────────────────────────────
# SHARED LIVE STATE
# ─────────────────────────────────────────────
state_lock = threading.Lock()
live_state = {
    "products": [],
    "alert_log": [],
    "last_updated": None,
    "is_checking": False,
    "total_alerts_fired": 0,
    "monitor_started": datetime.now().isoformat(),
    "check_interval_mins": CHECK_INTERVAL_MINS,
    "alerts_configured": {
        "discord": bool(DISCORD_WEBHOOK_URL),
        "email":   bool(EMAIL_FROM),
        "sms":     bool(TWILIO_ACCOUNT_SID),
    }
}
alerted_cache = {}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("restock_monitor.log"),
    ]
)
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# DASHBOARD LOCAL API SERVER
# ─────────────────────────────────────────────
class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/state":
            with state_lock:
                data = json.dumps(live_state, default=str)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data.encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


def start_dashboard_server():
    server = HTTPServer(("localhost", DASHBOARD_PORT), DashboardHandler)
    log.info(f"Dashboard API running on http://localhost:{DASHBOARD_PORT}/api/state")
    server.serve_forever()


# ─────────────────────────────────────────────
# SCRAPING
# ─────────────────────────────────────────────
def parse_price(price_text: str):
    if not price_text:
        return None
    cleaned = "".join(c for c in price_text if c.isdigit() or c == ".")
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def check_with_playwright(product: dict, config: dict) -> dict:
    result = {"in_stock": False, "price": None, "error": None}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--no-zygote",
                    "--single-process",
                ]
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
            )
            page = context.new_page()
            try:
                page.goto(product["url"], timeout=30000, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)

                atc = config.get("add_to_cart_selector")
                if atc:
                    atc_btn = page.query_selector(atc)
                    if atc_btn and atc_btn.is_visible():
                        result["in_stock"] = True

                for oos_sel in config.get("out_of_stock_selectors", []):
                    oos_el = page.query_selector(oos_sel)
                    if oos_el and oos_el.is_visible():
                        result["in_stock"] = False
                        break

                price_sel = config.get("price_selector")
                if price_sel:
                    price_el = page.query_selector(price_sel)
                    if price_el:
                        result["price"] = parse_price(price_el.inner_text())
            except Exception as e:
                result["error"] = str(e)
                log.warning(f"    Playwright page error on {product['store']} — {product['name']}: {str(e)[:120]}")
            finally:
                browser.close()
    except Exception as e:
        result["error"] = f"Browser launch failed: {str(e)}"
        log.warning(f"    Browser launch error on {product['store']} — {product['name']}: {str(e)[:120]}")
    return result


def check_with_requests(product: dict, config: dict) -> dict:
    from bs4 import BeautifulSoup
    result = {"in_stock": False, "price": None, "error": None}
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        )
    }
    try:
        resp = requests.get(product["url"], headers=headers, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        atc = config.get("add_to_cart_selector")
        if atc and soup.select_one(atc):
            result["in_stock"] = True
        for oos_sel in config.get("out_of_stock_selectors", []):
            if soup.select_one(oos_sel):
                result["in_stock"] = False
                break
        price_sel = config.get("price_selector")
        if price_sel:
            price_el = soup.select_one(price_sel)
            if price_el:
                result["price"] = parse_price(price_el.get_text())
    except Exception as e:
        result["error"] = str(e)
    return result


def is_price_acceptable(price, product: dict) -> bool:
    max_p = product.get("max_price") or MAX_PRICE_THRESHOLD
    if not max_p:
        return True
    if price is None:
        return True
    return price <= max_p


def check_single_product(product: dict) -> dict:
    store_cfg = STORE_CONFIGS.get(product["store"])
    if not store_cfg:
        return {
            "store": product["store"], "name": product["name"],
            "url": product["url"], "max_price": product.get("max_price"),
            "status": "error", "price": None,
            "last_checked": datetime.now().isoformat(),
            "error": "No store config found",
        }
    try:
        if store_cfg.get("use_playwright"):
            result = check_with_playwright(product, store_cfg)
        else:
            result = check_with_requests(product, store_cfg)
    except Exception as e:
        result = {"in_stock": False, "price": None, "error": str(e)}

    status = "error" if result.get("error") else ("in-stock" if result["in_stock"] else "out-of-stock")
    return {
        "store": product["store"],
        "name": product["name"],
        "url": product["url"],
        "max_price": product.get("max_price"),
        "status": status,
        "price": result.get("price"),
        "last_checked": datetime.now().isoformat(),
        "error": result.get("error"),
    }


# ─────────────────────────────────────────────
# ALERTS
# ─────────────────────────────────────────────
def send_discord_alert(product: dict, price):
    if not DISCORD_WEBHOOK_URL:
        return
    price_str = f"${price:.2f}" if price else "Price unknown"
    payload = {
        "username": "PokéRestock Bot",
        "embeds": [{
            "title": f"🔔 IN STOCK — {product['name']}",
            "url": product["url"],
            "color": 0xFFCB05,
            "fields": [
                {"name": "Store", "value": product["store"], "inline": True},
                {"name": "Price", "value": price_str, "inline": True},
                {"name": "Link",  "value": f"[Buy now]({product['url']})", "inline": False},
            ],
            "footer": {"text": f"Detected at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"},
        }],
    }
    try:
        r = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        r.raise_for_status()
        log.info(f"Discord alert sent for {product['name']}")
    except Exception as e:
        log.error(f"Discord alert failed: {e}")


def send_email_alert(product: dict, price):
    if not all([EMAIL_FROM, EMAIL_TO, EMAIL_PASSWORD]):
        return
    price_str = f"${price:.2f}" if price else "Price unknown"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🔔 IN STOCK: {product['name']} @ {product['store']}"
    msg["From"]    = EMAIL_FROM
    msg["To"]      = EMAIL_TO
    html_body = f"""
    <html><body style="font-family:sans-serif;background:#f5f5f5;padding:20px;">
      <div style="max-width:500px;margin:auto;background:white;border-radius:12px;
                  padding:24px;border:1px solid #e0e0e0;">
        <h2 style="color:#2a75bb;margin-top:0;">🔔 Pokémon TCG Restock Alert</h2>
        <table style="width:100%;border-collapse:collapse;font-size:15px;">
          <tr><td style="padding:8px 0;color:#888;">Product</td>
              <td style="padding:8px 0;font-weight:bold;">{product['name']}</td></tr>
          <tr><td style="padding:8px 0;color:#888;">Store</td>
              <td style="padding:8px 0;">{product['store']}</td></tr>
          <tr><td style="padding:8px 0;color:#888;">Price</td>
              <td style="padding:8px 0;color:#2a9d5c;font-weight:bold;">{price_str}</td></tr>
          <tr><td style="padding:8px 0;color:#888;">Time</td>
              <td style="padding:8px 0;">{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</td></tr>
        </table>
        <a href="{product['url']}"
           style="display:inline-block;margin-top:16px;padding:12px 24px;
                  background:#FFCB05;color:#1a1a1a;text-decoration:none;
                  border-radius:8px;font-weight:bold;">Buy Now →</a>
      </div>
    </body></html>"""
    msg.attach(MIMEText(html_body, "html"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        log.info(f"Email alert sent for {product['name']}")
    except Exception as e:
        log.error(f"Email alert failed: {e}")


def send_sms_alert(product: dict, price):
    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER, TWILIO_TO_NUMBER]):
        return
    try:
        from twilio.rest import Client
        price_str = f"${price:.2f}" if price else "unknown price"
        body = (
            f"RESTOCK ALERT 🎴\n{product['name']}\n"
            f"Store: {product['store']}\nPrice: {price_str}\n{product['url']}"
        )
        Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN).messages.create(
            body=body, from_=TWILIO_FROM_NUMBER, to=TWILIO_TO_NUMBER
        )
        log.info(f"SMS alert sent for {product['name']}")
    except Exception as e:
        log.error(f"SMS alert failed: {e}")


def fire_alerts(product: dict, price):
    send_discord_alert(product, price)
    send_email_alert(product, price)
    send_sms_alert(product, price)


def product_key(product: dict) -> str:
    return hashlib.md5(f"{product['store']}:{product['url']}".encode()).hexdigest()


# ─────────────────────────────────────────────
# MAIN CHECK CYCLE
# ─────────────────────────────────────────────
def check_all_products():
    log.info(f"━━━ Starting check cycle ({len(WATCHLIST)} products, parallel) ━━━")
    now = time.time()

    with state_lock:
        live_state["is_checking"] = True

    results = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        future_to_product = {executor.submit(check_single_product, p): p for p in WATCHLIST}
        for future in as_completed(future_to_product):
            product = future_to_product[future]
            try:
                result = future.result()
                results.append(result)
                price_str = f"@ ${result['price']:.2f}" if result.get("price") else ""
                log.info(
                    f"  {'✓' if result['status'] != 'error' else '✗'} "
                    f"{result['store']} — {result['name']}: "
                    f"{result['status'].upper()} {price_str}"
                )
            except Exception as e:
                log.error(f"  ✗ {product['store']} — {product['name']}: {e}")

    for result in results:
        if result["status"] == "in-stock":
            product = next((p for p in WATCHLIST if p["url"] == result["url"]), None)
            if product and is_price_acceptable(result["price"], product):
                key = product_key(product)
                last_alerted = alerted_cache.get(key, 0)
                if now - last_alerted > ALERT_COOLDOWN_SECS:
                    log.info(f"  🔔 RESTOCK — {result['name']} @ {result['store']}!")
                    fire_alerts(product, result["price"])
                    alerted_cache[key] = now
                    with state_lock:
                        live_state["total_alerts_fired"] += 1
                        live_state["alert_log"].insert(0, {
                            "time":  datetime.now().strftime("%H:%M:%S"),
                            "store": result["store"],
                            "name":  result["name"],
                            "price": result["price"],
                            "url":   result["url"],
                        })
                        live_state["alert_log"] = live_state["alert_log"][:50]

    url_order = {p["url"]: i for i, p in enumerate(WATCHLIST)}
    results.sort(key=lambda r: url_order.get(r["url"], 999))

    with state_lock:
        live_state["products"]     = results
        live_state["last_updated"] = datetime.now().isoformat()
        live_state["is_checking"]  = False

    in_stock_count = sum(1 for r in results if r["status"] == "in-stock")
    log.info(f"━━━ Cycle complete — {in_stock_count}/{len(results)} in stock ━━━\n")


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────
def main():
    log.info("=" * 55)
    log.info("Pokémon TCG Restock Monitor starting...")
    log.info(f"Monitoring {len(WATCHLIST)} products across {len(set(p['store'] for p in WATCHLIST))} stores")
    log.info(f"Check interval: every {CHECK_INTERVAL_MINS} minute(s)")
    log.info(f"Alerts: Discord={'✓' if DISCORD_WEBHOOK_URL else '✗'} | Email={'✓' if EMAIL_FROM else '✗'} | SMS={'✓' if TWILIO_ACCOUNT_SID else '✗'}")
    log.info(f"Dashboard API: http://localhost:{DASHBOARD_PORT}/api/state")
    log.info(f"Open dashboard.html in your browser to see live data")
    log.info("=" * 55)

    server_thread = threading.Thread(target=start_dashboard_server, daemon=True)
    server_thread.start()

    check_all_products()
    schedule.every(CHECK_INTERVAL_MINS).minutes.do(check_all_products)

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
