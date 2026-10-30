export interface SteamPlayer {
  steamid: string;
  communityvisibilitystate: number;
  profilestate: number;
  personaname: string;
  profileurl: string;
  avatar: string;
  avatarmedium: string;
  avatarfull: string;
  avatarhash: string;
  lastlogoff: number;
  personastate: number;
  realname?: string;
  primaryclanid?: string;
  timecreated?: number;
  personastateflags?: number;
  loccountrycode?: string;
  locstatecode?: string;
}

export interface Category {
  id: number;
  description: string;
}

export interface Genre {
  id: string;
  description: string;
}

export interface PriceOverview {
  currency: string;
  price_in_cents: number;
  final_formatted: string;
  discount_percentage: number;
}

export interface Metacritic {
  score: number;
  url: string;
}

export interface SteamGame {
  appid: number;
  game_type: string;
  game_name: string;
  is_free: boolean;
  detailed_description: string;
  header_image: string;
  website?: string;
  recommendations: number;
  release_date: string;
  esrb_rating: string;
  developers: string[];
  publishers: string[];
  categories: Category[];
  genres: Genre[];
  price_overview: PriceOverview;
  metacritic?: Metacritic;
  screenshots: string[];
  tags: string[];
}

export interface DealsGGPrices {
  retail_price: number;
  retail_price_low: number;
  keyshop_price: number;
  keyshop_price_low: number;
}

export interface DealsGGItem {
  appid: number;
  name: string;
  url: string;
  image_url: string;
  prices: DealsGGPrices;
  currency: string;
}

// A deal from the server's deals service
export interface Deal extends DealsGGItem {
  best_price: number; // cheapest of Steam and keyshop
  discount: number; // 0-1, against the Steam price
}

export type DealsKind = "wishlist" | "library";

export interface DealsResult {
  kind: DealsKind;
  steam_id: string;
  max_price: number;
  sort: string;
  games_total: number;
  games_scanned: number;
  rate_limited: boolean;
  stats: {
    games_found: number;
    lowest_deal: number | null;
    total_retail: number;
    total_deal: number;
  };
  deals: Deal[];
}

export interface KeyStatus {
  is_set: boolean;
  hint: string;
}

export interface Settings {
  steam_api_key: KeyStatus;
  deals_api_key: KeyStatus;
  discord_linked: boolean;
}

export interface SettingsUpdate {
  steam_api_key?: string;
  deals_api_key?: string;
  remove?: ("steam_api_key" | "deals_api_key")[];
}

export interface Me {
  steam_id: string;
  persona_name: string;
  avatar_url: string;
  discord_linked: boolean;
}

export interface ResolvedSteamUser {
  steamid: string;
  persona_name: string;
  profile_url: string;
  avatar_full: string;
  wishlist_count: number;
}

export type ListProps = {
  steamId: string;
  maxPrice: number | null;
};
