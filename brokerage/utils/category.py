"""
Utility functions for categorizing markets based on their metadata.
"""


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
    
    # Priority 3: Infer from title/question/description
    text_parts = [
        market_data.get('title') or '',
        market_data.get('question') or '',
        market_data.get('description') or '',
    ]
    text = ' '.join(text_parts).lower()
    
    infer_mapping = {
        'sports': 'Sports',
        'game': 'Sports',
        'match': 'Sports',
        'nfl': 'Sports',
        'nba': 'Sports',
        'soccer': 'Sports',
        'football': 'Sports',
        'election': 'Politics',
        'political': 'Politics',
        'vote': 'Politics',
        'government': 'Politics',
        'congress': 'Politics',
        'senate': 'Politics',
        'parliament': 'Politics',
        'economy': 'Economy',
        'stock': 'Economy',
        'gdp': 'Economy',
        'inflation': 'Economy',
        'unemployment': 'Economy',
        'market': 'Economy',
        'bitcoin': 'Crypto',
        'ethereum': 'Crypto',
        'crypto': 'Crypto',
        'blockchain': 'Crypto',
        'defi': 'Crypto',
        'nft': 'Crypto',
        'web3': 'Crypto',
        'ai': 'Technology',
        'tech': 'Technology',
        'software': 'Technology',
        'apple': 'Technology',
        'google': 'Technology',
        'meta': 'Technology',
        'tesla': 'Technology',
        'spacex': 'Technology',
        'elon': 'Technology',
        'climate': 'Environment',
        'environment': 'Environment',
        'temperature': 'Environment',
        'carbon': 'Environment',
        'warming': 'Environment',
        'war': 'Geopolitics',
        'russia': 'Geopolitics',
        'ukraine': 'Geopolitics',
        'israel': 'Geopolitics',
        'gaza': 'Geopolitics',
        'iran': 'Geopolitics',
        'china': 'Geopolitics',
        'north korea': 'Geopolitics',
        'ceasefire': 'Geopolitics',
        'conflict': 'Geopolitics',
        'gta': 'Technology',  # GTA VI games/entertainment
        'album': 'Technology',  # Entertainment/culture
        'rihanna': 'Technology',  # Entertainment
        'music': 'Technology',  # Entertainment
    }
    
    for keyword, category in infer_mapping.items():
        if keyword in text:
            return category
    
    return 'Other'
