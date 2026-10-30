import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { errorDetail, fetchSettings, saveSettings } from "../api";
import type { KeyStatus, SettingsUpdate } from "../types/steam";

const KeyField = ({
  label,
  status,
  value,
  onChange,
  getKeyUrl,
  note,
}: {
  note: string;
  label: string;
  status?: KeyStatus;
  value: string;
  onChange: (value: string) => void;
  getKeyUrl: string;
}) => {
  const [shown, setShown] = useState(false);

  return (
    <div className="ds-field">
      <div className="ds-field-head">
        <label className="ds-field-label">{label}</label>
        <span className={`ds-key-status${status?.is_set ? " set" : ""}`}>
          {status?.is_set ? `Saved ${status.hint}` : "Not set"}
        </span>
      </div>
      <div className="ds-input-row">
        <input
          type={shown ? "text" : "password"}
          className="ds-steam-input"
          placeholder={
            status?.is_set ? "Enter a new key to replace it" : "Paste your key"
          }
          value={value}
          onChange={(e) => onChange(e.target.value)}
          autoComplete="off"
          spellCheck={false}
        />
        <button
          type="button"
          className="ds-sort-btn"
          onClick={() => setShown(!shown)}
        >
          {shown ? "Hide" : "Show"}
        </button>
      </div>
      <div className="ds-field-help">{note}</div>
      <a
        className="ds-field-help"
        href={getKeyUrl}
        target="_blank"
        rel="noopener noreferrer"
      >
        Get a key →
      </a>
    </div>
  );
};

const SettingsPage = () => {
  const queryClient = useQueryClient();
  const { data: settings, isLoading } = useQuery({
    queryKey: ["settings"],
    queryFn: fetchSettings,
  });

  const [steamKey, setSteamKey] = useState("");
  const [dealsKey, setDealsKey] = useState("");

  const save = useMutation({
    mutationFn: saveSettings,
    onSuccess: (saved) => {
      queryClient.setQueryData(["settings"], saved);
      setSteamKey("");
      setDealsKey("");
    },
  });

  const update: SettingsUpdate = {};
  if (steamKey.trim()) update.steam_api_key = steamKey.trim();
  if (dealsKey.trim()) update.deals_api_key = dealsKey.trim();
  const hasChanges = Object.keys(update).length > 0;

  if (isLoading) return <div className="ds-status">Loading settings...</div>;

  return (
    <form
      className="ds-panel"
      onSubmit={(e) => {
        e.preventDefault();
        if (hasChanges) save.mutate(update);
      }}
    >
      <h2 className="ds-panel-title">Settings</h2>
      <p className="ds-panel-text">
        Your keys are checked with Steam and GG.deals, then stored encrypted
        on the server. They are never shown again in full. Leave a box empty
        to keep the saved key.
      </p>

      <KeyField
        label="Steam API key"
        status={settings?.steam_api_key}
        value={steamKey}
        onChange={setSteamKey}
        getKeyUrl="https://steamcommunity.com/dev/apikey"
        note="Needed for My Library and Find Steam ID. Wishlist scans work without it."
      />

      <KeyField
        label="GG.deals API key"
        status={settings?.deals_api_key}
        value={dealsKey}
        onChange={setDealsKey}
        getKeyUrl="https://gg.deals/api/"
        note="Needed for every deal scan."
      />

      <div className="ds-field">
        <div className="ds-field-head">
          <label className="ds-field-label">Discord</label>
          <span className={`ds-key-status${settings?.discord_linked ? " set" : ""}`}>
            {settings?.discord_linked ? "Linked" : "Not linked"}
          </span>
        </div>
        <div className="ds-field-help">
          Type /link in a Discord server that has DealScout to use the
          /wishlist and /library commands with your keys.
        </div>
      </div>

      <div className="ds-form-footer">
        <button
          type="submit"
          className="ds-scan-btn"
          disabled={!hasChanges || save.isPending}
        >
          {save.isPending ? "CHECKING..." : "SAVE"}
        </button>
        {save.isError && (
          <span className="ds-form-msg error">{errorDetail(save.error)}</span>
        )}
        {save.isSuccess && !hasChanges && (
          <span className="ds-form-msg success">Saved.</span>
        )}
      </div>
    </form>
  );
};

export default SettingsPage;
