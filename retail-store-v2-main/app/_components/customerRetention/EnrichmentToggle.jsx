import React, { useEffect, useState } from "react";
import Toggle from "@leafygreen-ui/toggle";
import Badge from "@leafygreen-ui/badge";
import { Body } from "@leafygreen-ui/typography";
import { useSelector, useDispatch } from "react-redux";
import { setFabricEnrichmentEnabled } from "@/redux/slices/CustomerRetentionSlice";

// Live switch for the Fabric real-time enrichment path. The on/off state lives
// in Redux (not local component state) so it persists as the user moves between
// the shop and cart pages, and it is synced from the backend on mount so it
// always reflects the true server state. Flipping it calls the /api/enrichment
// proxy (which hits the retention backend). Turning it ON also clears the
// current user's cached churn score so the next signal fires a fresh, live
// Fabric scoring call.
const EnrichmentToggle = () => {
  const dispatch = useDispatch();
  const selectedUser = useSelector((state) => state.User.selectedUser);
  const enabled = useSelector(
    (state) => state.CustomerRetention.fabricEnrichmentEnabled
  );
  const [busy, setBusy] = useState(false);

  // Sync the toggle with the backend's actual state on mount.
  useEffect(() => {
    let cancelled = false;
    fetch("/api/enrichment")
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (
          !cancelled &&
          data &&
          typeof data.fabric_enrichment_enabled === "boolean"
        ) {
          dispatch(setFabricEnrichmentEnabled(data.fabric_enrichment_enabled));
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [dispatch]);

  const handleChange = async (checked) => {
    dispatch(setFabricEnrichmentEnabled(checked)); // optimistic
    setBusy(true);
    try {
      const res = await fetch("/api/enrichment", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          state: checked ? "on" : "off",
          uid: selectedUser?._id,
        }),
      });
      if (!res.ok) {
        dispatch(setFabricEnrichmentEnabled(!checked)); // revert on failure
      }
    } catch {
      dispatch(setFabricEnrichmentEnabled(!checked));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: "10px",
        padding: "10px 14px",
        margin: "8px 4px 0",
        border: "1px solid #E8EDEB",
        borderRadius: "8px",
        background: "#F9FBFA",
      }}
    >
      <Toggle
        size="small"
        checked={enabled}
        disabled={busy}
        onChange={handleChange}
        aria-label="Toggle Fabric real-time enrichment"
      />
      <Body weight="medium" style={{ flex: 1 }}>
        Fabric real-time enrichment
      </Body>
      <Badge variant={enabled ? "green" : "lightgray"}>
        {enabled ? "ON" : "OFF"}
      </Badge>
    </div>
  );
};

export default EnrichmentToggle;
