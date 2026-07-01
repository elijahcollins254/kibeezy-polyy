"""
Utility functions for categorizing markets based on their metadata.
"""
import re

# This is just for initial setup for easy to categorise markets, allow admin to change category. Drop down.


def _contains_keyword(text, keyword):
    """
    Check if keyword appears in text with word boundaries to avoid partial matches.
    E.g., "market" won't match in "supermarket".
    """
    # Use word boundary regex to match whole words
    pattern = r'\b' + re.escape(keyword) + r'\b'
    return bool(re.search(pattern, text, re.IGNORECASE))


def extract_category(market_data):
    """
    Extract or infer category from market data.
    
    Priority: category field → tags → infer from keywords
    
    Args:
        market_data: Dict with market info (title, question, tags, category, etc.)
    
    Returns:
        str: Category name or 'Other'
    """
    # Priority 1: Explicit category field
    if market_data.get('category'):
        return market_data.get('category')
    
    # Priority 2: Check tags
    if market_data.get('tags'):
        tags = market_data.get('tags', [])
        if isinstance(tags, list) and len(tags) > 0:
            tag_mapping = {
                'sports': 'Sports',
                'politics': 'Politics',
                'election': 'Politics',
                'economy': 'Economy',
                'crypto': 'Crypto',
                'bitcoin': 'Crypto',
                'ethereum': 'Crypto',
                'tech': 'Technology',
                'technology': 'Technology',
                'ai': 'Technology',
                'environment': 'Environment',
                'climate': 'Environment',
                'geo': 'Geopolitics',
                'geopolitics': 'Geopolitics',
                'war': 'Geopolitics',
            }
            for tag in tags:
                tag_lower = str(tag).lower()
                for key, category in tag_mapping.items():
                    if key in tag_lower:
                        return category
    
    # Priority 3: Infer from title/question/description using word boundaries
    text_parts = [
        market_data.get('title') or '',
        market_data.get('question') or '',
        market_data.get('description') or '',
    ]
    text = ' '.join(text_parts).lower()
    
    # Check SPORTS FIRST (highest priority) - most specific
    sports_keywords = [
        'world cup', 'nfl', 'nba', 'nhl', 'mlb', 'pga', 'wimbledon',
        'super bowl', 'world series', 'stanley cup', 'champions league',
        'soccer', 'football', 'basketball', 'baseball', 'hockey', 'tennis',
        'golf', 'rugby', 'cricket', 'olympics', 'playoff', 'championship',
        'game', 'match', 'team', 'player', 'coach', 'score', 'win',
        'mvp', 'coach', 'draft', 'trade', 'season', 'tournament',
    ]
    for keyword in sports_keywords:
        if _contains_keyword(text, keyword):
            return 'Sports'
    
    # Check POLITICS
    politics_keywords = [
        'election', 'political', 'vote', 'government', 'congress',
        'senate', 'parliament', 'president', 'candidate', 'campaign',
        'democrat', 'republican', 'biden', 'trump', 'harris',
    ]
    for keyword in politics_keywords:
        if _contains_keyword(text, keyword):
            return 'Politics'
    
    # Check GEOPOLITICS (war, conflict)
    geopolitics_keywords = [
        'war', 'conflict', 'ceasefire', 'russia', 'ukraine', 'israel',
        'gaza', 'iran', 'china', 'north korea', 'invasion', 'attack',
        'military', 'troops', 'army', 'border', 'treaty', 'deal',
    ]
    for keyword in geopolitics_keywords:
        if _contains_keyword(text, keyword):
            return 'Geopolitics'
    
    # Check CRYPTO
    crypto_keywords = [
        'bitcoin', 'ethereum', 'crypto', 'blockchain', 'defi',
        'nft', 'web3', 'btc', 'eth', 'token', 'altcoin',
        'halving', 'eth2', 'dapps', 'smart contract',
    ]
    for keyword in crypto_keywords:
        if _contains_keyword(text, keyword):
            return 'Crypto'
    
    # Check TECHNOLOGY
    tech_keywords = [
        'ai', 'artificial intelligence', 'tech', 'technology', 'software',
        'apple', 'google', 'meta', 'tesla', 'spacex', 'elon',
        'ipo', 'startup', 'app', 'gta', 'game', 'release',
        'album', 'rihanna', 'music', 'artist', 'entertainment',
    ]
    for keyword in tech_keywords:
        if _contains_keyword(text, keyword):
            return 'Technology'
    
    # Check ENVIRONMENT
    environment_keywords = [
        'climate', 'environment', 'temperature', 'carbon', 'warming',
        'emissions', 'pollution', 'renewable', 'green', 'solar',
    ]
    for keyword in environment_keywords:
        if _contains_keyword(text, keyword):
            return 'Environment'
    
    # Check ECONOMY (least specific - check last)
    economy_keywords = [
        'economy', 'stock', 'gdp', 'inflation', 'unemployment',
        'interest rate', 'fed', 'recession', 'growth', 'earnings',
    ]
    for keyword in economy_keywords:
        if _contains_keyword(text, keyword):
            return 'Economy'
    
    return 'Other'


def extract_subcategory(market_data, category):
    """
    Extract or infer subcategory/league/topic from market data given its category.
    """
    if not category or category == 'Other':
        return None

    # Check tags first for subcategory if available
    tags = market_data.get('tags', [])
    if isinstance(tags, list) and len(tags) > 0:
        for tag in tags:
            tag_str = str(tag).upper()
            if tag_str in ['NFL', 'NBA', 'EPL', 'BTC', 'ETH', 'SOL', 'AI', 'UCL']:
                mapping = {'BTC': 'Bitcoin', 'ETH': 'Ethereum', 'SOL': 'Solana', 'UCL': 'Champions League'}
                return mapping.get(tag_str, tag_str)

    # Infer from text
    text_parts = [
        market_data.get('title') or '',
        market_data.get('question') or '',
        market_data.get('description') or '',
    ]
    text = ' '.join(text_parts).lower()

    if category == 'Sports':
        if any(_contains_keyword(text, kw) for kw in ['nfl', 'super bowl', 'superbowl', 'patriots', 'seahawks', 'chiefs']):
            return 'NFL'
        if any(_contains_keyword(text, kw) for kw in ['nba', 'basketball', 'lakers', 'celtics', 'warriors', 'curry', 'lebron']):
            return 'NBA'
        if any(_contains_keyword(text, kw) for kw in ['epl', 'premier league', 'chelsea', 'arsenal', 'liverpool', 'manchester united', 'man city', 'manchester city', 'spurs', 'tottenham']):
            return 'EPL'
        if any(_contains_keyword(text, kw) for kw in ['la liga', 'la-liga', 'real madrid', 'barcelona', 'laliga']):
            return 'La Liga'
        if any(_contains_keyword(text, kw) for kw in ['champions league', 'ucl', 'champions-league']):
            return 'Champions League'
        if any(_contains_keyword(text, kw) for kw in ['tennis', 'wimbledon', 'us open', 'nadal', 'federer', 'djokovic', 'open']):
            return 'Tennis'
        if any(_contains_keyword(text, kw) for kw in ['f1', 'formula 1', 'formula-1', 'grand prix', 'hamilton', 'verstappen']):
            return 'Formula 1'

    elif category == 'Crypto':
        if any(_contains_keyword(text, kw) for kw in ['bitcoin', 'btc', 'satoshi']):
            return 'Bitcoin'
        if any(_contains_keyword(text, kw) for kw in ['ethereum', 'eth', 'vitalik']):
            return 'Ethereum'
        if any(_contains_keyword(text, kw) for kw in ['solana', 'sol']):
            return 'Solana'

    elif category == 'Politics':
        if any(_contains_keyword(text, kw) for kw in ['biden', 'trump', 'harris', 'presidential', 'democrat', 'republican', 'senate', 'congress', 'white house']):
            return 'US Politics'
        if any(_contains_keyword(text, kw) for kw in ['ruto', 'odinga', 'kenya', 'kenyan', 'gachagua', 'nairobi']):
            return 'Kenyan Politics'
        if any(_contains_keyword(text, kw) for kw in ['uk', 'starmer', 'sunak', 'labour', 'tory', 'parliament']):
            return 'UK Politics'

    elif category == 'Technology':
        if any(_contains_keyword(text, kw) for kw in ['ai', 'openai', 'chatgpt', 'gpt', 'claude', 'gemini', 'anthropic', 'sam altman', 'nvidia']):
            return 'AI'
        if any(_contains_keyword(text, kw) for kw in ['apple', 'iphone', 'macbook', 'ios', 'ipad']):
            return 'Apple'
        if any(_contains_keyword(text, kw) for kw in ['gta', 'grand theft auto', 'rockstar', 'playstation', 'xbox', 'nintendo', 'gaming', 'game']):
            return 'Gaming'
        if any(_contains_keyword(text, kw) for kw in ['spacex', 'starship', 'mars', 'nasa', 'moon', 'sls', 'rocket']):
            return 'Space'

    elif category == 'Geopolitics':
        if any(_contains_keyword(text, kw) for kw in ['russia', 'ukraine', 'putin', 'zelensky', 'kiev', 'moscow', 'nato']):
            return 'Russia-Ukraine'
        if any(_contains_keyword(text, kw) for kw in ['israel', 'gaza', 'hamas', 'iran', 'palestine', 'middle east', 'hezbollah', 'lebanon']):
            return 'Middle East'
        if any(_contains_keyword(text, kw) for kw in ['china', 'taiwan', 'south china sea', 'beijing', 'taipei']):
            return 'Asia-Pacific'

    return None

