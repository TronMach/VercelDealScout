import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { errorDetail, resolveSteamId } from "../api";

const FindSteamId = ({
  onScanWishlist,
}: {
  onScanWishlist: (steamId: string) => void;
}) => {
  const [query, setQuery] = useState("");

  const lookup = useMutation({ mutationFn: resolveSteamId });
  const user = lookup.data;

  return (
    <div className="ds-panel">
      <h2 className="ds-panel-title">Find a Steam ID</h2>
      <p className="ds-panel-text">
        Look up a friend to scan their wishlist. Paste their Steam profile
        link, custom profile name, or an ID you already have.
      </p>

      <form
        className="ds-input-row"
        onSubmit={(e) => {
          e.preventDefault();
          if (query.trim()) {
            lookup.mutate(query.trim());
          }
        }}
      >
        <input
          type="text"
          className="ds-steam-input"
          placeholder="https://steamcommunity.com/id/yourname"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          spellCheck={false}
        />
        <button
          type="submit"
          className="ds-scan-btn"
          disabled={!query.trim() || lookup.isPending}
        >
          {lookup.isPending ? "LOOKING..." : "FIND"}
        </button>
      </form>

      {lookup.isError && (
        <div className="ds-error ds-gap">{errorDetail(lookup.error)}</div>
      )}

      {user && (
        <div className="ds-profile ds-gap">
          <img className="ds-profile-avatar" src={user.avatar_full} alt="" />
          <div className="ds-profile-body">
            <a
              className="ds-profile-name"
              href={user.profile_url}
              target="_blank"
              rel="noopener noreferrer"
            >
              {user.persona_name}
            </a>
            <div className="ds-profile-id">
              <span className="ds-stat-lbl">Steam ID</span>{" "}
              <span className="ds-stat-val">{user.steamid}</span>
            </div>
            <div className="ds-stat">
              {user.wishlist_count > 0 ? (
                <>
                  <span className="ds-stat-val">{user.wishlist_count}</span>{" "}
                  <span className="ds-stat-lbl">games on wishlist</span>
                </>
              ) : (
                <span className="ds-warn-text">
                  No wishlist games visible. The wishlist is empty, or the
                  profile's game details are private.
                </span>
              )}
            </div>
            <div className="ds-profile-actions">
              <button
                className="ds-scan-btn"
                onClick={() => onScanWishlist(user.steamid)}
                disabled={user.wishlist_count === 0}
              >
                SCAN WISHLIST
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="ds-help-box ds-gap">
        <div className="ds-field-label">Other ways to find it</div>
        <ul>
          <li>
            In Steam, open the profile, right-click and choose{" "}
            <b>Copy Page URL</b>, then paste it above.
          </li>
          <li>
            For a wishlist to show up, its owner sets <b>Game details</b> to
            Public in their Steam profile's privacy settings.
          </li>
        </ul>
      </div>
    </div>
  );
};

export default FindSteamId;
