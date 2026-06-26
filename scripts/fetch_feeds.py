#!/usr/bin/env python3
"""
PLN Feed Fetcher — José Roberto Mendoza
========================================
Genera ../data/feeds.json con artículos de todas tus fuentes.

Uso:
    pip install -r requirements.txt
    python3 fetch_feeds.py

Para automatizar en GitHub Actions:
    Crea .github/workflows/update_feeds.yml con un cron trigger que
    ejecute este script y haga commit del feeds.json actualizado.
"""

import json
import time
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import requests
from bs4 import BeautifulSoup

# ════════════════════════════════════════════════════════════════
# FUENTES POR CATEGORÍA
# Agrega o elimina fuentes sin tocar el resto del código.
# Para LinkedIn/Instagram usa RSSHub (ver sección al final del archivo).
# ════════════════════════════════════════════════════════════════
SOURCES = {

    'tech-ia': [
        # Hacker News via hnrss.org (más limpio que el API directa)
        {'name': 'Hacker News',        'url': 'https://hnrss.org/frontpage?count=25&points=100'},
        {'name': 'Ars Technica',       'url': 'https://feeds.arstechnica.com/arstechnica/index'},
        {'name': 'TechCrunch',         'url': 'https://techcrunch.com/feed/'},
        {'name': 'r/technology',       'url': 'https://www.reddit.com/r/technology/.rss'},
        {'name': 'r/artificial',       'url': 'https://www.reddit.com/r/artificial/.rss'},
        {'name': 'r/MachineLearning',  'url': 'https://www.reddit.com/r/MachineLearning/.rss'},
        # Descomenta si quieres el blog de Platzi (verificar URL vigente)
        # {'name': 'Platzi Blog', 'url': 'https://platzi.com/blog/feed/'},
    ],

    'educacion': [
        {'name': 'r/edtech',           'url': 'https://www.reddit.com/r/edtech/.rss'},
        {'name': 'r/Futurology',       'url': 'https://www.reddit.com/r/Futurology/.rss'},
        # Medium — perfil Freddy Vega (si tiene publicaciones):
        # {'name': 'Freddy Vega Medium', 'url': 'https://medium.com/feed/@freddyvega'},
        # Substack — agrega newsletters que sigas:
        # {'name': 'Newsletter X',      'url': 'https://nombre.substack.com/feed'},
    ],

    'coaching': [
        {'name': 'Harvard Business Review', 'url': 'https://feeds.hbr.org/harvardbusiness'},
        {'name': 'r/Leadership',            'url': 'https://www.reddit.com/r/Leadership/.rss'},
        {'name': 'r/Entrepreneur',          'url': 'https://www.reddit.com/r/Entrepreneur/.rss'},
        # Blog Christian Van Der Henst (verificar URL vigente):
        # {'name': 'CVander Blog',     'url': 'https://cvander.com/feed/'},
        # Pablo Lomelí (Substack u otro):
        # {'name': 'Pablo Lomelí',     'url': 'https://pablolomeli.substack.com/feed'},
    ],

    'psicologia': [
        {'name': 'r/SportPsychology',  'url': 'https://www.reddit.com/r/SportPsychology/.rss'},
        {'name': 'r/psychology',       'url': 'https://www.reddit.com/r/psychology/.rss'},
        # Psychology Today tiene múltiples feeds por tema; ajusta el slug:
        {'name': 'Psychology Today',   'url': 'https://www.psychologytoday.com/intl/blog/the-psychology-entrepreneurs/feed'},
    ],

    'juegos': [
        {'name': 'r/boardgames',       'url': 'https://www.reddit.com/r/boardgames/.rss'},
        {'name': 'r/cooperativegames', 'url': 'https://www.reddit.com/r/cooperativegames/.rss'},
        {'name': 'r/TeamBuilding',     'url': 'https://www.reddit.com/r/TeamBuilding/.rss'},
        # BGG se obtiene via API XML (ver fetch_bgg_hotness más abajo)
    ],

    'geopolitica': [
        {'name': 'r/geopolitics',      'url': 'https://www.reddit.com/r/geopolitics/.rss'},
        {'name': 'r/worldnews',        'url': 'https://www.reddit.com/r/worldnews/.rss'},
    ],

    'startup': [
        {'name': 'r/startups',         'url': 'https://www.reddit.com/r/startups/.rss'},
        {'name': 'Product Hunt',       'url': 'https://www.producthunt.com/feed'},
    ],
}

# ════════════════════════════════════════════════════════════════
# CONFIG
# ════════════════════════════════════════════════════════════════
OUTPUT   = Path(__file__).parent.parent / 'data' / 'feeds.json'
MAX_EACH = 15          # artículos máximos por feed
DELAY    = 0.6         # segundos entre requests (no saturar servidores)
TIMEOUT  = 15          # timeout HTTP en segundos

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (PLN-Fetcher/1.0; GitHub Pages; +github.com/josemendoza)'
}

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-7s %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger('pln')


# ════════════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════════════
def make_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:14]


def parse_date(entry) -> str:
    for field in ('published_parsed', 'updated_parsed', 'created_parsed'):
        t = getattr(entry, field, None)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc).isoformat()
            except Exception:
                pass
    return datetime.now(timezone.utc).isoformat()


def extract_image(entry) -> str | None:
    # 1. media:thumbnail (Twitter, YouTube, Reddit)
    thumb = getattr(entry, 'media_thumbnail', None)
    if thumb and isinstance(thumb, list) and thumb[0].get('url'):
        return thumb[0]['url']

    # 2. media:content con tipo imagen
    for mc in getattr(entry, 'media_content', []):
        if mc.get('url') and mc.get('type', '').startswith('image'):
            return mc['url']

    # 3. enclosures (podcasts, artículos con imagen adjunta)
    for enc in getattr(entry, 'enclosures', []):
        if enc.get('type', '').startswith('image'):
            return enc.get('href') or enc.get('url')

    # 4. Primera <img> dentro del HTML del resumen o contenido
    html = ''
    if hasattr(entry, 'summary'):
        html = entry.summary or ''
    elif getattr(entry, 'content', None):
        html = entry.content[0].value or ''

    if html:
        soup = BeautifulSoup(html, 'lxml')
        img  = soup.find('img')
        if img and img.get('src') and img['src'].startswith('http'):
            return img['src']

    return None


def clean_summary(entry, max_chars=220) -> str:
    html = ''
    if hasattr(entry, 'summary'):
        html = entry.summary or ''
    elif getattr(entry, 'content', None):
        html = entry.content[0].value or ''

    text = BeautifulSoup(html, 'lxml').get_text(separator=' ')
    text = ' '.join(text.split())
    return (text[:max_chars] + '…') if len(text) > max_chars else text


# ════════════════════════════════════════════════════════════════
# FETCHERS
# ════════════════════════════════════════════════════════════════
def fetch_rss(name: str, url: str, category: str) -> list[dict]:
    """Parsea un feed RSS/Atom y retorna lista de items normalizados."""
    log.info(f'  RSS  {name:<30} {url[:55]}')
    items = []
    try:
        feed = feedparser.parse(url, request_headers=HEADERS)
        if feed.bozo and not feed.entries:
            log.warning(f'       Feed malformado: {feed.bozo_exception}')
            return items

        for entry in feed.entries[:MAX_EACH]:
            link  = getattr(entry, 'link', None)
            title = (getattr(entry, 'title', '') or '').strip()
            if not link or not title:
                continue

            items.append({
                'id':        make_id(link),
                'title':     title,
                'url':       link,
                'source':    name,
                'category':  category,
                'summary':   clean_summary(entry),
                'image':     extract_image(entry),
                'published': parse_date(entry),
                'score':     None,
                'tags':      [],
            })

        log.info(f'       → {len(items)} items')
    except Exception as exc:
        log.warning(f'       ERROR: {exc}')
    return items


def fetch_hacker_news_api(limit: int = 20) -> list[dict]:
    """
    Complementa el RSS de HN con datos del API oficial:
    incluye score de votos y es más fresco que el feed.
    """
    log.info(f'  HN   API oficial (top {limit} stories)')
    items = []
    base  = 'https://hacker-news.firebaseio.com/v0'
    try:
        ids = requests.get(f'{base}/topstories.json', headers=HEADERS, timeout=TIMEOUT).json()
        for story_id in ids[:limit]:
            time.sleep(0.08)
            story = requests.get(f'{base}/item/{story_id}.json', headers=HEADERS, timeout=TIMEOUT).json()
            if not story or not story.get('url') or story.get('dead') or story.get('deleted'):
                continue
            items.append({
                'id':        f'hn-{story["id"]}',
                'title':     story.get('title', '').strip(),
                'url':       story['url'],
                'source':    'Hacker News',
                'category':  'tech-ia',
                'summary':   '',
                'image':     None,
                'published': datetime.fromtimestamp(story.get('time', 0), tz=timezone.utc).isoformat(),
                'score':     story.get('score', 0),
                'tags':      ['hackernews'],
            })
        log.info(f'       → {len(items)} items')
    except Exception as exc:
        log.warning(f'       HN API ERROR: {exc}')
    return items


def fetch_bgg_hotness() -> list[dict]:
    """BoardGameGeek: los juegos de mesa más populares del momento (XML API pública)."""
    log.info('  BGG  Hotness API (juegos en tendencia)')
    items = []
    try:
        r    = requests.get('https://www.boardgamegeek.com/xmlapi2/hot?type=boardgame',
                            headers=HEADERS, timeout=TIMEOUT)
        soup = BeautifulSoup(r.text, 'lxml-xml')
        for rank, item in enumerate(soup.find_all('item')[:12], start=1):
            name_tag  = item.find('name')
            thumb_tag = item.find('thumbnail')
            bgg_id    = item.get('id', '')
            if not name_tag:
                continue
            items.append({
                'id':        f'bgg-{bgg_id}',
                'title':     f'🎲 BGG Hot #{rank}: {name_tag.get("value", "")}',
                'url':       f'https://boardgamegeek.com/boardgame/{bgg_id}',
                'source':    'BoardGameGeek',
                'category':  'juegos',
                'summary':   'Actualmente en tendencia en BoardGameGeek.',
                'image':     (thumb_tag.text.strip() if thumb_tag else None),
                'published': datetime.now(timezone.utc).isoformat(),
                'score':     None,
                'tags':      ['boardgames', 'hotness'],
            })
        log.info(f'       → {len(items)} items')
    except Exception as exc:
        log.warning(f'       BGG ERROR: {exc}')
    return items


# ════════════════════════════════════════════════════════════════
# REDES CERRADAS (LinkedIn, Instagram)
# ════════════════════════════════════════════════════════════════
# LinkedIn e Instagram no tienen APIs públicas gratuitas.
# La mejor estrategia es usar RSSHub, que convierte perfiles públicos en RSS.
#
# OPCIÓN A — instancia pública de RSSHub (puede fallar por rate-limit):
#   Freddy Vega LinkedIn:  https://rsshub.app/linkedin/user/freddyvega
#   Pablo Lomelí LinkedIn: https://rsshub.app/linkedin/user/pablolomeli
#   CVander LinkedIn:      https://rsshub.app/linkedin/user/cvander
#
# OPCIÓN B — instancia propia (más confiable):
#   git clone https://github.com/DIYgod/RSSHub
#   npm install && npm start
#   Luego usa http://localhost:1200/linkedin/user/freddyvega
#
# OPCIÓN C — Zapier/Make (no-code):
#   Monitorea un perfil de LinkedIn y exporta a webhook → tu feeds.json
#
# Para activar, descomenta las líneas de SOURCES['coaching'] o 'educacion':
#
# def fetch_rsshub_profiles():
#     profiles = [
#         ('Freddy Vega',              'https://rsshub.app/linkedin/user/freddyvega',  'educacion'),
#         ('Pablo Lomelí',             'https://rsshub.app/linkedin/user/pablolomeli', 'coaching'),
#         ('Christian Van Der Henst',  'https://rsshub.app/linkedin/user/cvander',     'coaching'),
#     ]
#     items = []
#     for name, url, cat in profiles:
#         items += fetch_rss(name, url, cat)
#         time.sleep(DELAY)
#     return items


# ════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════
def main():
    log.info('╔══ PLN Feed Fetcher ══════════════════════════════╗')
    log.info(f'╚  Destino: {OUTPUT}')

    all_items: list[dict] = []
    seen_ids:  set[str]   = set()

    def add(new_items: list[dict]):
        for it in new_items:
            if it['id'] not in seen_ids:
                seen_ids.add(it['id'])
                all_items.append(it)

    # 1. RSS por categoría
    for category, sources in SOURCES.items():
        log.info(f'\n── {category.upper()} ──')
        for src in sources:
            add(fetch_rss(src['name'], src['url'], category))
            time.sleep(DELAY)

    # 2. Hacker News API (más datos que su RSS)
    log.info('\n── HACKER NEWS API ──')
    add(fetch_hacker_news_api(limit=15))

    # 3. BoardGameGeek Hotness
    log.info('\n── BOARDGAMEGEEK ──')
    add(fetch_bgg_hotness())

    # 4. (Opcional) Perfiles RSSHub
    # log.info('\n── RSSHUB PROFILES ──')
    # add(fetch_rsshub_profiles())

    # Ordenar por fecha descendente
    all_items.sort(key=lambda x: x.get('published', ''), reverse=True)

    # Escribir JSON
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        'meta': {
            'generated': datetime.now(timezone.utc).isoformat(),
            'total':     len(all_items),
        },
        'items': all_items,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')

    log.info(f'\n✅  {len(all_items)} artículos guardados en {OUTPUT.name}')
    log.info('   Abre pln-flipboard.html en el navegador para verlos.')


if __name__ == '__main__':
    main()
