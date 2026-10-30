import axios from "axios";

import type {
  SteamPlayer,
  DealsKind,
  DealsResult,
  Settings,
  SettingsUpdate,
  ResolvedSteamUser,
  Me,
} from "./types/steam";

export const fetchSteamUser = async (
  steam_id: string,
): Promise<SteamPlayer> => {
  try {
    const res = await axios.get(`/api/steam/user/${steam_id}`);
    return res.data;
  } catch (error) {
    if (axios.isAxiosError(error)) {
      console.log("Status:", error.response?.status);
      console.log("Message:", error.response?.data.detail);
    }
    throw error;
  }
};

// Scans a wishlist or library on the server. maxPrice null uses the server default ($10).
export const fetchDeals = async (
  kind: DealsKind,
  steam_id: string,
  maxPrice: number | null,
): Promise<DealsResult> => {
  const params = maxPrice === null ? {} : { max_price: maxPrice };
  const res = await axios.get(`/api/deals/${kind}/${steam_id}`, { params });
  return res.data;
};

// The signed-in user, or null when signed out
export const fetchMe = async (): Promise<Me | null> => {
  try {
    const res = await axios.get("/api/auth/me");
    return res.data;
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 401)
      return null;
    throw error;
  }
};

export const logout = async (): Promise<void> => {
  await axios.post("/api/auth/logout", {});
};

export const LOGIN_URL = "/api/auth/steam/login";

export const fetchSettings = async (): Promise<Settings> => {
  const res = await axios.get("/api/settings");
  return res.data;
};

export const saveSettings = async (
  update: SettingsUpdate,
): Promise<Settings> => {
  const res = await axios.put("/api/settings", update);
  return res.data;
};

export const resolveSteamId = async (
  query: string,
): Promise<ResolvedSteamUser> => {
  const res = await axios.get("/api/steam/resolve", { params: { query } });
  return res.data;
};

// Pulls the server's error message out of a failed request
export const errorDetail = (error: unknown): string => {
  if (axios.isAxiosError(error))
    return error.response?.data?.detail ?? error.message;
  return String(error);
};
