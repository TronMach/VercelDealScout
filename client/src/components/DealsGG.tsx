import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { errorDetail, fetchDeals } from "../api";
import GameCard from "./GameCard";
import type { Deal, DealsKind, ListProps } from "../types/steam";

type SortKey = "found" | "price" | "discount" | "name";

// Same orderings as server/src/deals_service.py sort_deals, using the server's best_price and discount
const sortDeals = (deals: Deal[], sort: SortKey): Deal[] => {
  const list = [...deals];
  if (sort === "price") list.sort((a, b) => a.best_price - b.best_price);
  if (sort === "discount") list.sort((a, b) => b.discount - a.discount);
  if (sort === "name")
    list.sort((a, b) =>
      a.name.localeCompare(b.name, undefined, { sensitivity: "base" }),
    );
  return list;
};

const DealsGG = ({
  kind,
  steamId,
  maxPrice,
}: ListProps & { kind: DealsKind }) => {
  const PAGE_SIZE = 20;
  const [filter, setFilter] = useState("");
  const [sort, setSort] = useState<SortKey>("found");
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);

  const [prevReset, setPrevReset] = useState({ filter, sort, maxPrice, steamId, kind });
  if (
    prevReset.filter !== filter ||
    prevReset.sort !== sort ||
    prevReset.maxPrice !== maxPrice ||
    prevReset.steamId !== steamId ||
    prevReset.kind !== kind
  ) {
    setPrevReset({ filter, sort, maxPrice, steamId, kind });
    setVisibleCount(PAGE_SIZE);
  }

  const { data, isLoading, error } = useQuery({
    queryKey: ["deals", kind, steamId, maxPrice],
    queryFn: () => fetchDeals(kind, steamId, maxPrice),
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  const filtered = useMemo(() => {
    const needle = filter.toLowerCase();
    const list = (data?.deals ?? []).filter(
      (g) => needle === "" || g.name.toLowerCase().includes(needle),
    );
    return sortDeals(list, sort);
  }, [data, filter, sort]);

  if (isLoading)
    return (
      <div className="ds-status">
        Scanning {kind === "wishlist" ? "wishlist" : "library"} for deals...
      </div>
    );
  if (error) return <div className="ds-rate-limit">{errorDetail(error)}</div>;
  if (!data) return null;

  const { stats } = data;

  return (
    <div>
      {data.rate_limited && (
        <div className="ds-rate-limit">
          GG.deals rate limited part of the scan — showing {stats.games_found}{" "}
          deals found so far. Try again in a minute for the rest.
        </div>
      )}
      {data.games_scanned < data.games_total && (
        <div className="ds-status">
          Checked the first {data.games_scanned} of {data.games_total} games.
        </div>
      )}

      {stats.games_found > 0 && (
        <div className="ds-stats">
          <div className="ds-stat">
            <span className="ds-stat-val">{stats.games_found}</span>{" "}
            <span className="ds-stat-lbl">games found</span>
          </div>
          {stats.lowest_deal !== null && (
            <div className="ds-stat">
              <span className="ds-stat-val">
                ${stats.lowest_deal.toFixed(2)}
              </span>{" "}
              <span className="ds-stat-lbl">lowest deal</span>
            </div>
          )}
          <div className="ds-stat">
            <span className="ds-stat-val">
              ${stats.total_retail.toFixed(2)}
            </span>{" "}
            <span className="ds-stat-lbl">total retail</span>
          </div>
          <div className="ds-stat">
            <span className="ds-stat-val">${stats.total_deal.toFixed(2)}</span>{" "}
            <span className="ds-stat-lbl">total if bought now</span>
          </div>
        </div>
      )}

      <div className="ds-controls">
        <input
          className="ds-filter"
          placeholder="Filter games..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        {(["price", "discount", "name"] as SortKey[]).map((s) => (
          <button
            key={s}
            className={`ds-sort-btn${sort === s ? " active" : ""}`}
            onClick={() => setSort(sort === s ? "found" : s)}
          >
            {s === "price"
              ? "Price ↑"
              : s === "discount"
                ? "Discount ↓"
                : "Name A–Z"}
          </button>
        ))}
      </div>

      {stats.games_found === 0 && (
        <div className="ds-status">
          No games under ${data.max_price.toFixed(2)} right now.
        </div>
      )}

      <div className="ds-game-list">
        {filtered.slice(0, visibleCount).map((deal) => (
          <GameCard key={deal.appid} game={deal} />
        ))}
      </div>

      {visibleCount < filtered.length && (
        <div className="ds-load-more">
          <button
            className="ds-sort-btn"
            onClick={() => setVisibleCount((c) => c + PAGE_SIZE)}
          >
            Load More
          </button>
        </div>
      )}
    </div>
  );
};

export default DealsGG;
