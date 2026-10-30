import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import DealsGG from "./components/DealsGG";
import SettingsPage from "./components/SettingsPage";
import FindSteamId from "./components/FindSteamId";
import { fetchMe, fetchSettings, logout, LOGIN_URL } from "./api";

type Mode = "wishlist" | "library";
type Page = "deals" | "find" | "settings";

// Messages the server adds to the URL after Steam sign-in or Discord linking
const readLoginNotice = (): { text: string; error: boolean } | null => {
  const params = new URLSearchParams(window.location.search);
  let notice: { text: string; error: boolean } | null = null;
  if (params.get("login_error"))
    notice = { text: params.get("login_error")!, error: true };
  else if (params.get("discord") === "linked")
    notice = { text: "Discord is linked. Try /wishlist in Discord.", error: false };
  else if (params.get("discord") === "link_expired")
    notice = {
      text: "That Discord link expired or was already used. Type /link again.",
      error: true,
    };
  if (window.location.search)
    window.history.replaceState(null, "", window.location.pathname);
  return notice;
};

function App() {
  const queryClient = useQueryClient();
  const [notice] = useState(readLoginNotice);
  const [page, setPage] = useState<Page>("deals");
  const [steamId, setSteamId] = useState("");
  const [submittedId, setSubmittedId] = useState("");
  const [active, setActive] = useState(false);
  const [mode, setMode] = useState<Mode>("wishlist");
  const [maxPrice, setMaxPrice] = useState<number | "">("");

  const {
    data: me,
    isLoading: meLoading,
    isError: serverDown,
  } = useQuery({ queryKey: ["me"], queryFn: fetchMe, retry: false });

  const { data: settings } = useQuery({
    queryKey: ["settings"],
    queryFn: fetchSettings,
    enabled: !!me,
  });
  const keysMissing = settings !== undefined && !settings.deals_api_key.is_set;

  const signOut = useMutation({
    mutationFn: logout,
    onSuccess: () => {
      queryClient.clear();
      setActive(false);
      setPage("deals");
    },
  });

  const handleScan = () => {
    if (!me) return;
    // An empty box scans your own wishlist
    setSubmittedId(mode === "library" ? me.steam_id : steamId.trim() || me.steam_id);
    setActive(true);
  };

  const scanWishlist = (id: string) => {
    setSteamId(id);
    setSubmittedId(id);
    setMode("wishlist");
    setActive(true);
    setPage("deals");
  };

  if (meLoading)
    return (
      <div className="ds-app">
        <div className="ds-server-status checking">Connecting to server...</div>
      </div>
    );

  if (serverDown)
    return (
      <div className="ds-app">
        <div className="ds-server-status error">
          Server is offline. Start the backend and refresh.
        </div>
      </div>
    );

  const noticeBox = notice && (
    <div className={notice.error ? "ds-rate-limit" : "ds-status"}>
      {notice.text}
    </div>
  );

  if (!me)
    return (
      <div className="ds-app">
        <nav className="ds-nav">
          <div className="ds-logo">
            DEAL<span>SCOUT</span>
          </div>
        </nav>
        {noticeBox}
        <div className="ds-panel">
          <h2 className="ds-panel-title">Find cheap prices for your Steam games</h2>
          <p className="ds-panel-text">
            DealScout checks your Steam wishlist and library against GG.deals
            and lists the games you can get for under your price. Sign in with
            Steam, then add your own free GG.deals API key. DealScout never
            sees your Steam password.
          </p>
          <a className="ds-scan-btn" href={LOGIN_URL}>
            SIGN IN WITH STEAM
          </a>
        </div>
      </div>
    );

  return (
    <div className="ds-app">
      <nav className="ds-nav">
        <div className="ds-logo">
          DEAL<span>SCOUT</span>
        </div>
        <div className="ds-nav-links">
          {(
            [
              ["deals", "Deals"],
              ["find", "Find Steam ID"],
              ["settings", "Settings"],
            ] as [Page, string][]
          ).map(([p, label]) => (
            <button
              key={p}
              className={`ds-nav-link${page === p ? " active" : ""}`}
              onClick={() => setPage(p)}
            >
              {label}
              {p === "settings" && keysMissing && (
                <span className="ds-nav-dot" />
              )}
            </button>
          ))}
          <span className="ds-nav-user">
            {me.avatar_url && (
              <img className="ds-nav-avatar" src={me.avatar_url} alt="" />
            )}
            {me.persona_name}
          </span>
          <button
            className="ds-nav-link"
            onClick={() => signOut.mutate()}
            disabled={signOut.isPending}
          >
            Sign out
          </button>
        </div>
      </nav>

      {noticeBox}

      {keysMissing && page !== "settings" && (
        <div className="ds-rate-limit">
          Add your GG.deals API key to start scanning.{" "}
          <button className="ds-link-btn" onClick={() => setPage("settings")}>
            Go to Settings
          </button>
        </div>
      )}

      {page === "settings" && <SettingsPage />}

      {page === "find" && <FindSteamId onScanWishlist={scanWishlist} />}

      {page === "deals" && (
        <>
          <header className="ds-header">
            <div className="ds-input-row">
              <div className="ds-mode-toggle">
                <button
                  className={`ds-mode-btn${mode === "wishlist" ? " active" : ""}`}
                  onClick={() => {
                    setMode("wishlist");
                    setActive(false);
                  }}
                >
                  Wishlist
                </button>
                <button
                  className={`ds-mode-btn${mode === "library" ? " active" : ""}`}
                  onClick={() => {
                    setMode("library");
                    setActive(false);
                  }}
                >
                  My Library
                </button>
              </div>
              <input
                type="text"
                className="ds-steam-input"
                placeholder={
                  mode === "library"
                    ? "Your library"
                    : "Your wishlist, or a friend's SteamID64"
                }
                value={mode === "library" ? "" : steamId}
                onChange={(e) => mode === "wishlist" && setSteamId(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleScan()}
                disabled={mode === "library"}
              />
              <input
                type="number"
                className="ds-steam-input"
                placeholder="Max $10"
                value={maxPrice}
                onChange={(e) =>
                  setMaxPrice(e.target.value === "" ? "" : Number(e.target.value))
                }
                style={{ maxWidth: "120px" }}
                min={0}
                step={0.01}
              />
              <button
                className="ds-scan-btn"
                onClick={handleScan}
                disabled={keysMissing}
              >
                SCAN
              </button>
            </div>
          </header>

          {active && (
            <DealsGG
              kind={mode}
              steamId={submittedId}
              maxPrice={maxPrice === "" ? null : maxPrice}
            />
          )}
        </>
      )}
    </div>
  );
}

export default App;
