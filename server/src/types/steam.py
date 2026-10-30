from pydantic import BaseModel
from typing import Literal, Optional
    
class SteamPlayer(BaseModel):
    steamid: str
    persona_name: str
    profile_url: str
    avatar_full: str
    real_name: str
    country_code: str
    state_code: str

class Category(BaseModel):
    id: int
    description: str

class Genre(BaseModel):
    id: str
    description: str

class PriceOverview(BaseModel):
    currency: str
    price_in_cents: int
    final_formatted: str
    discount_percentage: int

class Metacritic(BaseModel):
    score: int
    url: str

class SteamGame(BaseModel):
    appid: int
    game_type: str
    game_name: str
    is_free: Optional[bool]
    detailed_description: str
    header_image: str
    website: Optional[str] = None
    recommendations: Optional[int] = None
    release_date: Optional[str] = None
    esrb_rating: Optional[str] = None
    developers: list[str]
    publishers: list[str]
    categories: list[Category]
    genres: list[Genre]
    price_overview: Optional[PriceOverview] = None
    metacritic: Optional[Metacritic] = None
    screenshots: list[str]
    tags: list[str]

class Wishlist(BaseModel):
  steamid: str
  appid: int
  priority: int
  
class Library(BaseModel):
  steamid: str
  appid: int
  playtime_minutes: int
  
class DealsGGPrices(BaseModel):
  retail_price: float
  retail_price_low: float
  keyshop_price: float
  keyshop_price_low: float
  
class DealsGG(BaseModel):
  appid: int
  name: str
  url: str
  image_url: str
  prices: DealsGGPrices
  currency: str
  
class Deal(DealsGG):
  # Cheapest of the Steam and keyshop prices
  best_price: float
  # 0-1, how much cheaper best_price is than the Steam price
  discount: float

class DealStats(BaseModel):
  games_found: int
  lowest_deal: Optional[float]
  total_retail: float
  total_deal: float

class DealsResult(BaseModel):
  kind: str
  steam_id: str
  max_price: float
  sort: str
  games_total: int
  games_scanned: int
  rate_limited: bool
  stats: DealStats
  deals: list[Deal]

class KeyStatus(BaseModel):
    is_set: bool
    hint: str

class Settings(BaseModel):
    steam_api_key: KeyStatus
    deals_api_key: KeyStatus
    discord_linked: bool

class SettingsUpdate(BaseModel):
    # None or empty keeps the saved key
    steam_api_key: Optional[str] = None
    deals_api_key: Optional[str] = None
    # Names of keys to delete: 'steam_api_key', 'deals_api_key'
    remove: Optional[list[Literal['steam_api_key', 'deals_api_key']]] = None

class Me(BaseModel):
    steam_id: str
    persona_name: str
    avatar_url: str
    discord_linked: bool

class ResolvedSteamUser(BaseModel):
    steamid: str
    persona_name: str
    profile_url: str
    avatar_full: str
    wishlist_count: int

def correct_user_account_response() -> dict:
    return {
        "response": {
            "players": []
        }
    }
    
def correct_user_wishlist_response() -> dict:
    return {
        "response": {
            "items": []
        }
    }
    
def correct_user_library_response() -> dict:
    return {
        "response": {
            "games": []
        }
    }
    
def correct_game_data_response(appid: str) -> dict:
    return {
        appid: {
            "data": {}
        }
    }